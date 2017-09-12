#!/usr/bin/env python
#coding=utf8

import SocketServer
import sys
import pymysql.cursors
import datetime
from time import sleep,ctime
import string
import re
if sys.getdefaultencoding() != 'utf8' :
	reload(sys)
	sys.setdefaultencoding('utf8')

mysql_config = {
	"host": "localhost",
	"port": 3306,
	"user": "aprs",
	"passwd": "123456",
	"db": "aprs",
	"charset": "utf8",
	"cursorclass": pymysql.cursors.DictCursor
}

def generate(callsign):
	# This method derived from the xastir project under a GPL license.
	seed = 0x73E2

	odd = True
	key = seed
	for char in callsign.upper():
		proc_char = ord(char)
		if odd:
			proc_char <<= 8
		key = key ^ proc_char
		odd = not odd
	key &= 0x7FFF
	return key

class My_server(SocketServer.BaseRequestHandler):
	def handle(self):
		#while True:
		data =self.request[0]
#		print(data.decode('utf-8'))
#		print(self.client_address,self.request[1])
		aprs_decode(data.decode('utf-8'))

def aprs_decode(data):
	print data
	#parameter=()
	aprs_data=data.split("\r\n")
	user_segments = re.search('user\s*([\w\-]+)\s*pass\s*([0-9]{5})(.*)',aprs_data[0])
	while True:
		if user_segments is not None:
			(user,passcode) = user_segments.groups()
			if passcode==generate(user) :
				#print aprs_data[1]
				while True:
					#检测APRS位置包（不带timestamp）
					packet_segments = re.search('([\w\-]+)>(.*):(=|!)([0-9.NS]{8})(/|D)([0-9.EW]{9})(>|\$|&|!)(.*)', aprs_data[1])
					if packet_segments is not None:
						(callsign, path, datatype, lat, tableid, long, symbolid, msg) = packet_segments.groups()
						to_mysql(callsign, path, datatype, lat, tableid, long, symbolid, msg, aprs_data[1])
						break
					#检测APRS位置包（带timestamp）
					packet_segments = re.search('([\w\-]+)>(.*):(@|/)([0-9z]{7})([0-9.NS]{8})(/|D)([0-9.EW]{9})(>|\$|&|!)(.*)', aprs_data[1])
					if packet_segments is not None:
						(callsign, path, timestamp, datatype, lat, tableid, long, symbolid, msg) = packet_segments.groups()
						to_mysql(callsign, path, datatype, lat, tableid, long, symbolid, msg, aprs_data[1])
						break
					#检测APRS天气包（不带timestamp）
					packet_segments = re.search('([\w\-]+)>(.*):(=|!)([0-9.NS]{8})(/|D)([0-9.EW]{9})_(.*)', aprs_data[1])
					if packet_segments is not None:
						(callsign, path, datatype, lat, tableid, long, symbolid, msg) = packet_segments.groups()
						to_mysql(callsign, path, datatype, lat, tableid, long, symbolid, msg, aprs_data[1])
						break
					#检测APRS天气包（带timestamp）
					packet_segments = re.search('([\w\-]+)>(.*):(/|@)([0-9z]{7})([0-9.NS]{8})(/|D)([0-9.EW]{9})_(.*)', aprs_data[1])
					if packet_segments is not None:
						(callsign, path, datatype, lat, tableid, long, symbolid, msg) = packet_segments.groups()
						to_mysql(callsign, path, datatype, lat, tableid, long, symbolid, msg, aprs_data[1])
						break
					#检测APRS位置包（不带timestamp, 压缩坐标）
					packet_segments = re.search('([\w\-]+)>(.*):('|`)(.{4})(.{4})($|/|`|]|')(.{2})(.{1})(.*)', aprs_data[1])
					if packet_segments is not None:
						(callsign, path, tableid, comp_lat, comp_long, symbolid, speed, comptype, msg) = packet_segments.groups()
						
			#			to_mysql(callsign, path, datatype, lat, tableid, long, symbolid, msg, aprs_data[1])
						break
			
	
		
def to_mysql(my_callsign, my_path, my_datatype, my_lat, my_tableid, my_long, my_symbolid, my_msg, my_rawdata):
	global connection
	aprspacket_sql="INSERT INTO aprspacket (`call`,datatype, lat, lon, `table`, symbol, msg, raw) VALUES (%s,%s,%s,%s,%s,%s,%s,%s);"
	lastpacket_sql="REPLACE INTO lastpacket (`call`, datatype, lat, lon, `table`, symbol, msg) VALUES (%s,%s,%s,%s,%s,%s,%s);"
	packetstatus_sql="INSERT INTO packetstats VALUES(curdate(),1) ON DUPLICATE KEY UPDATE packets=packets+1 ;"
	packetcount_sql="INSERT into aprspackethourcount values (DATE_FORMAT(now(), '%%Y-%%m-%%d %%H:00:00'), %s, 1) ON DUPLICATE KEY UPDATE pkts=pkts+1 ;"

	print " %s %s %s %s %s %s %s %s " % (my_callsign, my_path, my_datatype, my_lat, my_tableid, my_long, my_symbolid, my_msg)
	try:
		with connection.cursor() as cursor:
			cursor.execute(aprspacket_sql,(my_callsign, my_datatype, my_lat, my_long, my_tableid, my_symbolid, my_msg, my_rawdata))
		connection.commit()
		with connection.cursor() as cursor:
			cursor.execute(lastpacket_sql,(my_callsign, my_datatype, my_lat, my_long, my_tableid, my_symbolid, my_msg))
		connection.commit()
		with connection.cursor() as cursor:
			cursor.execute(packetcount_sql, (my_callsign))
		connection.commit()
		with connection.cursor() as cursor:
			cursor.execute(packetstatus_sql)
		connection.commit()
		print "Commit insert data"
	except Exception as e: 
		print "roolback with %s " % (e)
		connection.rollback()
			
def mysql_connect() :
	global connection
	#参考地址：https://github.com/PyMySQL/PyMySQL#installation
	while True:
		try:
			connection = pymysql.connect(**mysql_config)
			break
		except :
			print "Connect to mysql error, try again after 10s"
			sleep(60)
			continue
		

if __name__ == '__main__':
	mysql_connect()

	ip_port =('0.0.0.0',14580)
	obj =SocketServer.ThreadingUDPServer(ip_port,My_server)
	obj.daemon=True
	obj.serve_forever()
	while True:
		sleep(500)
		print ctime()
		try:
			connection.ping()
		except:
#			print "\nReconnecting Mysql db @ %s" % ctime()
			mysql_connect()
	connection.close()
