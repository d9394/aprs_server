#!/usr/bin/env python
#coding=utf8
import sys
sys.path.append("/home/test/aprs/aprs-python-master")
import socket
import pymysql.cursors
from time import sleep,ctime
import re
import aprslib
import threading
import Queue

mysql_config = {
	#"host": "localhost",
	#"port": 3306,
	"user": "aprs",
	"passwd": "aprs",
	"db": "aprs",
	"charset": "utf8",
	"cursorclass": pymysql.cursors.DictCursor,
	"connect_timeout":10,
	"unix_socket":'/var/run/mysqld/mysqld.sock',		#改用unix_socket连接mysql提高性能
}

upstream_server = ("china.aprs2.net",14580)  # 上游APRS服务器
forward_server = ("asia.aprs2.net",14580)  # 上游APRS服务器
callsign = "test"  # 替换为你的呼号
passcode = "12345"  # 替换为你的APRS-IS passcode
#filter = "b/B*/VR2*/XX9*"
filter = "r/35.0/103.0/2500" # 替换为你想要使用的APRS过滤器

aprspacket_sql="INSERT INTO aprspacket (`call`,datatype, lat, lon, `table`, symbol, msg, raw) VALUES ('%s','%s','%s','%s','%s','%s','%s','%s');"
lastpacket_sql="REPLACE INTO lastpacket (`call`, datatype, lat, lon, `table`, symbol, msg) VALUES ('%s','%s','%s','%s','%s','%s','%s');"
packetstatus_sql="INSERT INTO packetstats VALUES(curdate(),1) ON DUPLICATE KEY UPDATE packets=packets+1 ;"
packetcount_sql="INSERT into aprspackethourcount values (DATE_FORMAT(now(), '%%Y-%%m-%%d %%H:00:00'), '%s', 1) ON DUPLICATE KEY UPDATE pkts=pkts+1 ;"

data_queue = Queue.Queue(1000)  # SQL缓存队列大小:1000
aprs_queue = Queue.Queue(1000)  # 转发缓存队列大小:1000

aprs_datatype={
	'uncompressed':'=',
	'compressed':'=',
	'mic-e':'`',
	'object':';',
	'wx':'_',
	'status':'>',
	'message':':',
	'telemetry-message':'T',
}

def decimal_to_aprs(latitude, longitude):
	# 将十进制坐标转换为 APRS 格式
	lat_degrees = int(latitude)
	lat_minutes = abs(latitude - lat_degrees) * 60
	lat_direction = "N" if latitude >= 0 else "S"

	lon_degrees = int(longitude)
	lon_minutes = abs(longitude - lon_degrees) * 60
	lon_direction = "E" if longitude >= 0 else "W"

	# APRS 格式要求整数部分和小数部分之间有一个点
	lat_aprs = "%02d%04.2f%s" % (abs(lat_degrees), lat_minutes, lat_direction)
	lon_aprs = "%03d%04.2f%s" % (abs(lon_degrees), lon_minutes, lon_direction)

	return lat_aprs, lon_aprs
	
def aprs_decode(mycall, aprs):
	#print('raw packet: %s ' % aprs)
	data_queue.put(packetstatus_sql)
	try :
		data=aprslib.parse(aprs)
		lat,lon = decimal_to_aprs(data['latitude'], data['longitude'])
		try :
			datatype = aprs_datatype[data['format']]
		except :
			datatype = ','
		if 'weather' not in data:		#本站只记录定位包
			data_queue.put( aprspacket_sql % (data['from'][:16], datatype, lat, lon, data['symbol_table'][:1].replace("\\","\\\\").replace("'", "''"), data['symbol'][:1].replace("\\","\\\\").replace("'", "''"), (data['comment'].replace("'", "''"))[:200], (data['raw'].replace("\\","\\\\").replace("'", "''"))[:500]))
			data_queue.put( lastpacket_sql % (data['from'][:16], datatype,lat, lon, data['symbol_table'][:1].replace("\\","\\\\").replace("'", "''"), data['symbol'][:1].replace("\\","\\\\").replace("'", "''"), (data['comment'].replace("'", "''"))[:200]))
	except Exception as e:
		#print(u'无法解包：%s' % (aprs))
	#	print(u'%s\t错误原因：%s' % (ctime(),e))
		data_queue.put( aprspacket_sql % (mycall[:16], '', '', '', '','','', aprs[:500].replace("'", "''")))
		data = {}
	data_queue.put(packetcount_sql % mycall[:16])
	return data

def to_mysql():
	connection = None
	while True :
		if connection is None :
			connection = mysql_connect()
		if data_queue.qsize() > 0 :
			#print("当前序列总数 %d" % data_queue.qsize())
			try:
				with connection.cursor() as cursor:
					while data_queue.qsize() > 0 :				#一次性写入mysql
						cursor.execute(data_queue.get())
						data_queue.task_done()				#每次get()后task_done()保证队列计数器一致性
				connection.commit()						#一次性提交，提高mysql性能
			except Exception as e: 
				print("%s roolback reason: %s " % (ctime(), e))
				connection.rollback()
		else :
			try:
				connection.ping()
				sleep(1)
			except:
				connection = None
			
def mysql_connect() :
	#参考地址：https://github.com/PyMySQL/PyMySQL#installation
	while True:
		try:
			connection = pymysql.connect(**mysql_config)
			print(u'%s Mysql connect success' % (ctime()))
			break
		except Exception as e:
			print(u"%s : Connect to mysql error, try again after 5s : %s" % (ctime(), e))
			sleep(5)
			continue
	return connection

def connect_to_aprs_server(upt2aprs_server, callsign, passcode, filter):
	sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
	sock.connect(upt2aprs_server)
	login = "user %s pass %s vers python-aprs 1.0 filter %s\n" % (callsign, passcode, filter)
	#user N0CALL-1 pass 13023 vers python-aprs 1.0 filter b/B*
	sock.sendall(login.encode('utf-8'))
	return sock
	
def process_aprs_data(get_aprs):
	try:
	# 尝试使用 UTF-8 解码
		decoded_str = get_aprs.decode('utf-8')
	except UnicodeDecodeError:
		try:
		# 如果 UTF-8 失败，尝试使用 GB2312 解码
			decoded_str = get_aprs.decode('gb2312')
		except UnicodeDecodeError:
		# 如果两者都失败，使用默认解码
			try :
				decoded_str = get_aprs.decode()
			except UnicodeDecodeError :
				decoded_str = ""
				#print(u'接收包解码错误：%s' % get_aprs)
	callsign_segments = re.search(r'([A-Za-z0-9\-]+)>(.*)', decoded_str)			#分离出呼号
	if callsign_segments is not None :		#没有呼号的信息直接跳过
		try:
			data = aprs_decode(callsign_segments.groups()[0], decoded_str)
		#except aprslib.exceptions.ParseError:
		except Exception as e:
			#print(u"无法解析的数据: %s，错误原因：%s " %(decoded_str,e))
			pass

def aprs_tcp_client(timeout=30):
	sock = connect_to_aprs_server(t2aprs_server, callsign, passcode, filter)
	sock.settimeout(timeout)
	while True :
		try :
			get_packet = sock.recv(4096)			#接收上源服务器APRS信息
			for line in get_packet.split('\n'):
				if line:
					process_aprs_data(line)
			while aprs_queue.qsize() > 0 :			#向上源服务器发送APRS信息
				try :
					aprs_data = (aprs_queue.get()+"\n").encode('utf-8')
					aprs_queue.task_done()
					sock.sendall(aprs_data)
				except Exception as e:
					print("%s 转发aprs失败：%s" % (ctime(), e))
					break
		except socket.timeout:
			print("%s TCP Receiving data timed out" % (ctime()))
			break
		except Exception as e:
			print("%s Error receiving TCP data: %s" % (ctime(),e))
			break
	print("TCP连接关闭")
	sock.close()

def aprs_tcp_server():
	while True :
		sleep(1600)
	
def aprs_udp_server():
	mSocket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
	mSocket.bind(("0.0.0.0",14580)) 
	while True:
		recvData, (remoteHost, remotePort) = mSocket.recvfrom(1024)
		try :
			recvData=recvData.decode().strip()
			#print("%s Recv APRS UDP: %s\n from %s:%s" % (ctime(), recvData,remoteHost, remotePort))
			mSocket.sendto("R".encode("UTF-8"),(remoteHost, remotePort))
		except Exception as e :
			print(u'%s Recv %s:%s APRS UDP error: %s' % (ctime(),remoteHost, remotePort, recvData))
		else :
			if len(recvData)>0 :
				aprs_data=recvData.split("\r\n")
				user_segments = re.search('user\s*([\w\-]+)\s*pass\s*([0-9]{5})(.*)',aprs_data[0])
				if user_segments is not None:
					(user, passcode, _) = user_segments.groups()
					#print("UDP User %s Passcode %s" % (user,passcode))
					if int(passcode)==aprslib.passcode(str(user[0:user.find("-")])) :
						packet_data = aprs_decode(str(user),aprs_data[1])
						if ('weather' not in packet_data) and ('latitude' in packet_data):		#只转发定位包
							aprs_queue.put(aprs_data[1])

	mSocket.close()
"""
def aprs_udp_sent(msg):
	uSocket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
	#for m in msg.split("\r\n") :
		#uSocket.sendto(m.encode('utf-8'), forward_server)
	uSocket.sendto(msg.replace("\r\n","\n").encode('utf-8'), forward_server)
	print('%s Forward to %s Message: %s' %(ctime(), forward_server, msg))
	uSocket.close()
"""

## 线程状态管理
threads = {}
thread_targets = {
	'aprs_tcp_server': aprs_tcp_server,
	'aprs_udp_server': aprs_udp_server,
	'aprs_tcp_client': aprs_tcp_client,
	'to_mysql': to_mysql
}

# 启动线程
def start_thread(name, target):
	thread = threading.Thread(target=target, name=name)
	thread.setDaemon(True)  # 将线程设置为守护线程
	thread.start()
	threads[name] = thread
	print("%s Starting %s thread" % (ctime(),name))

# 检查线程状态
def check_threads():
	while True:
		for name, thread in threads.items():
			if not thread.is_alive():
				#print("%s : %s is not alive. Restarting..." % (ctime(),name))
				start_thread(name, thread_targets[name])
		sleep(5)  

if __name__ == '__main__':
	# 使用循环启动所有线程
	for name, target in thread_targets.items():
		start_thread(name, target)
	
	# 启动线程检查
	check_thread = threading.Thread(target=check_threads)
	check_thread.setDaemon(True)  # 将线程设置为守护线程
	check_thread.start()
	
	# 主线程保持运行
	try:
		while True:
			sleep(10)
	except KeyboardInterrupt:
		print("Shutting down...")
