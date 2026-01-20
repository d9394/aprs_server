#!/usr/bin/env python
#coding=utf8
import sys
sys.path.append("/home/ba7ib/aprs/aprs-python-master")
import aprslib
import socket
import pymysql.cursors
from time import sleep,ctime
import re
import threading
try:
    import queue as Queue
except:
    import Queue
import chardet

mysql_config = {
    #"host": "localhost",
    #"port": 3306,
    "user": "aprs",
    "passwd": "aprs",
    "db": "aprs",
    "charset": "utf8mb4",
    "cursorclass": pymysql.cursors.DictCursor,
    "connect_timeout":10,
    "unix_socket":'/run/mysqld/mysqld.sock',
}

t2aprs_server = ("asia.aprs2.net",14580)  # 上游APRS服务器
callsign = "test"  # 替换为你的呼号
passcode = ""  # 替换为你的APRS-IS passcode
#filter = "b/B*/VR2*/XX9*"
filter = "r/35.0/103.0/2500 -t/wt"  # 替换为你想要使用的APRS过滤器

aprspacket_sql="INSERT INTO aprspacket (`call`,datatype, lat, lon, `table`, symbol, msg, raw) VALUES ('%s','%s','%s','%s','%s','%s','%s','%s');"
lastpacket_sql="REPLACE INTO lastpacket (`call`, datatype, lat, lon, `table`, symbol, msg, speed) VALUES ('%s','%s','%s','%s','%s','%s','%s', %d);"
packetstatus_sql="INSERT INTO packetstats VALUES(curdate(),1) ON DUPLICATE KEY UPDATE packets=packets+1 ;"
packetcount_sql="INSERT into aprspackethourcount values (DATE_FORMAT(now(), '%%Y-%%m-%%d %%H:00:00'), '%s', 1) ON DUPLICATE KEY UPDATE pkts=pkts+1 ;"

data_queue = Queue.Queue(1000)  # SQL缓存队列大小:1000
aprs_queue = Queue.Queue(1000)  # 转发缓存队列大小:1000

aprs_datatype={
    'uncompressed':'!',
    'compressed':'=',
    'mic-e':'`',
    'object':';',
    'wx':'_',
    'status':'>',
    'message':':',
    'telemetry-message':'T',
}

"""
标识符符号与其功能的对应表
符号    功能类型    说明
=    位置报告（无时间戳）    基于压缩或未压缩符号表的位置报告
!    位置报告（无时间戳）    基于未压缩符号表的位置报告
/    位置报告（带时间戳）    带时间戳的未压缩位置报告
@    位置报告（带时间戳）    带时间戳的压缩位置报告
;    对象报告    特殊事件或对象报告
>    状态报告    发送电台或设备状态
_    天气报告    包含天气数据的报告
:    消息    短文本消息
?    查询    查询请求或命令
`    Mic-E 压缩位置报告    使用 Mic-E 压缩编码的位置报告
&    电台控制命令    用于电台控制或特殊指令
#    优先级或警报信息    主要用于紧急或高优先级信息
T    遥测数据    发送遥测数据（如传感器读数）
"""

def convert_speed_to_int(aprs_data):
    try:
        # 将 speed 字符串转换为整数
        speed_int = int(aprs_data['speed'])
        return speed_int
    except ValueError:
        # 如果转换失败，返回 0
        return 0

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
    # 初始化
    data = {}
    data_queue.put(packetstatus_sql)
    
    try:
        # 使用 aprslib 解析
        data = aprslib.parse(aprs)
        
        # --- 修复点 1: 检查是否存在坐标 ---
        # 只有存在经纬度时才进行坐标转换和后续存储逻辑
        if 'latitude' in data and 'longitude' in data:
            lat, lon = decimal_to_aprs(data['latitude'], data['longitude'])
            
            # 安全获取 format/datatype
            datatype = aprs_datatype.get(data.get('format', ''), ',')
            
            # 忽略气象数据 (weather)
            if 'weather' not in data:
                # --- 修复点 2: 安全生成 msg ---
                # 使用 .get(key, default) 避免 KeyError
                course = int(data.get('course', 0))
                speed_kmh = data.get('speed', 0)
                speed_knots = int(speed_kmh / 1.852) if speed_kmh else 0
                altitude_m = data.get('altitude', 0)
                altitude_ft = int(altitude_m * 3.281) if altitude_m else 0
                
                # 拼接速度航向信息
                movement_info = "%03d/%03d/A=%06d" % (course, speed_knots, altitude_ft)
                
                # 获取评论信息
                comment = data.get('comment', "")
                data['msg'] = movement_info + " " + comment
                
                # --- 修复点 3: 存入数据库队列 ---
                # 确保字段获取安全，并对特殊符号进行转义
                from_call = data.get('from', '')[:16]
                sym_table = data.get('symbol_table', '/')[:1].replace("\\", "\\\\").replace("'", "''")
                sym_code = data.get('symbol', '>')[:1].replace("\\", "\\\\").replace("'", "''")
                msg_content = data.get('msg', "")[:200].replace("'", "''")
                raw_packet = data.get('raw', "")[:500].replace("\\", "\\\\").replace("'", "''")
                
                # 安全获取速度值用于 lastpacket_sql
                # 建议在 convert_speed_to_int 内部也做安全检查
                try:
                    speed_val = convert_speed_to_int(data)
                except:
                    speed_val = 0

                data_queue.put(aprspacket_sql % (from_call, datatype, lat, lon, sym_table, sym_code, msg_content, raw_packet))
                data_queue.put(lastpacket_sql % (from_call, datatype, lat, lon, sym_table, sym_code, msg_content, speed_val))
        
        else:
            # 如果没有经纬度，可能是状态消息或短消息，你可以选择记录到另一张表或跳过
            # print(u"收到非定位包: %s" % aprs)
            pass

    except Exception as e:
        # 这里的 e 会告诉你具体的错误原因
        print(u'%s 无法解包：%s\n\t原因：%s' % (ctime(), aprs, e))
        # 存入错误日志/原始包记录
        data_queue.put(aprspacket_sql % (mycall[:16], '', '', '', '', '', '', aprs[:500].replace("'", "''")))
        data = {}
    
    data_queue.put(packetcount_sql % mycall[:16])
    return data

def to_mysql():
    print("Thread ID:%s, name : %s" % (hex(threading.current_thread().ident), "to_mysql"))
    connection = None
    while True :
        if connection is None :
            connection = mysql_connect()
        if data_queue.qsize() > 0 :
            #print("当前序列总数 %d" % data_queue.qsize())
            try:
                with connection.cursor() as cursor:
                    while data_queue.qsize() > 0 :
                        cursor.execute(data_queue.get())
                        data_queue.task_done()
                connection.commit()
            except Exception as e: 
                print("%s roolback reason: %s " % (ctime(), e))
                connection.rollback()
        else :
            try:
                connection.ping()
                sleep(5)
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

def process_aprs_data(get_aprs):
    """
    兼容 Python 2.7 和 3.x 的 APRS 数据处理函数
    """
    decoded_str = ""

    # --- 1. 智能解码逻辑 ---
    
    # 判断是否已经是“文本字符串”类型
    # Python 3: str
    # Python 2: unicode
    is_python3 = (sys.version_info[0] >= 3)
    
    # 定义“已经解码好的文本”类型
    text_type = str if is_python3 else unicode
    # 定义“需要解码的字节”类型
    bytes_type = bytes if is_python3 else str

    if isinstance(get_aprs, text_type):
        # 如果已经是文本字符串，直接使用
        decoded_str = get_aprs
    elif isinstance(get_aprs, bytes_type):
        # 如果是字节流，则需要使用 chardet 检测编码
        try:
            # chardet.detect 仅接受字节流
            result = chardet.detect(get_aprs)
            encoding = result['encoding']
            
            if encoding is None:
                # 无法检测编码时，尝试 UTF-8 或 GB2312
                try:
                    decoded_str = get_aprs.decode('utf-8')
                except UnicodeDecodeError:
                    try:
                        decoded_str = get_aprs.decode('gb2312')
                    except UnicodeDecodeError:
                        decoded_str = get_aprs.decode('latin-1', 'ignore')
            else:
                # 使用检测到的编码解码
                try:
                    decoded_str = get_aprs.decode(encoding)
                except (UnicodeDecodeError, LookupError):
                    # 如果检测出的编码不可用，回退到忽略错误的解码
                    decoded_str = get_aprs.decode('utf-8', 'ignore')
        except Exception as e:
            print("%s 编码识别过程出错: %s" % (time.ctime(), e))
            decoded_str = ""
    else:
        # 其他未知类型
        decoded_str = str(get_aprs)

    # --- 2. 业务逻辑处理 ---
    
    if not decoded_str:
        return

    # 使用正则分离出呼号
    # 注意：在 Py2 中，如果正则表达式是 unicode，decoded_str 也应该是 unicode
    callsign_segments = re.search(r'([A-Za-z0-9\-]+)>(.*)', decoded_str)
    
    if callsign_segments is not None:
        try:
            # 提取呼号 (正则分组第一个)
            source_callsign = callsign_segments.groups()[0]
            
            # 调用您的解码库 (假设 aprs_decode 已在外部定义)
            # data = aprs_decode(source_callsign, decoded_str)
            # 这里保持您原来的逻辑
            data = aprs_decode(source_callsign, decoded_str)
            
        except Exception as e:
            # 解析失败通常是因为数据格式不符合 APRS 标准，静默跳过
            # print("无法解析的数据: %s, 错误: %s" % (decoded_str, e))
            pass

'''
def connect_to_aprs_server(upt2aprs_server, callsign, passcode, filter):
....sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
....sock.connect(upt2aprs_server)
....login = "user %s pass %s vers python-aprs 1.0 filter %s\n" % (callsign, passcode, filter)
....#user N0CALL-1 pass 13023 vers python-aprs 1.0 filter b/B*
....sock.sendall(login.encode('utf-8'))
....return sock
'''

def connect_to_aprs_server(server_addr, call, pwd, aprs_filter_val):
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.connect(server_addr)
    
    login_str = "user %s pass %s vers python-aprs 1.0 filter %s\n" % (call, pwd, aprs_filter_val)
    
    # Python 3 必须转 bytes
    if sys.version_info[0] >= 3:
        payload = login_str.encode('utf-8')
    else:
        payload = str(login_str)
        
    sock.sendall(payload)
    return sock

def aprs_tcp_client(timeout=30, reconnect_delay=10):
    """
    健壮的 APRS TCP 客户端：支持自动重连和多版本兼容
    """
    print("Thread ID:%s, name : %s" % (hex(threading.current_thread().ident), "aprs_tcp_client"))
    
    while True: # 外部循环：负责重连
        sock = None
        try:
            print("%s 正在尝试连接服务器..." % ctime())
            
            # 使用全局变量建立连接
            # 这里的 filter 如果是你脚本里的变量名，请确保它已定义
            sock = connect_to_aprs_server(t2aprs_server, callsign, passcode, filter)
            sock.settimeout(timeout)
            print("%s 连接成功，开始监听数据流..." % ctime())

            while True: # 内部循环：负责正常通信
                try:
                    # --- 1. 接收处理 ---
                    raw_data = sock.recv(4096)
                    if not raw_data:
                        print("%s 服务器主动断开了连接 (收到空数据)。" % ctime())
                        break # 跳出内部循环，准备重连
                    
                    # 兼容处理：将字节转为字符串供业务逻辑使用
                    if sys.version_info[0] >= 3:
                        data_str = raw_data.decode('utf-8', 'ignore')
                    else:
                        data_str = raw_data
                    
                    for line in data_str.splitlines():
                        if line.strip():
                            # 交给已经修复好的 process_aprs_data 处理
                            process_aprs_data(line.strip())

                    # --- 2. 发送处理 ---
                    while aprs_queue.qsize() > 0:
                        try:
                            msg = aprs_queue.get_nowait()
                            
                            # 确保是字符串并加上换行符
                            if sys.version_info[0] >= 3 and isinstance(msg, bytes):
                                msg = msg.decode('utf-8', 'ignore')
                            
                            payload = msg + "\n"
                            
                            # Python 3 必须转为 bytes 发送
                            if sys.version_info[0] >= 3:
                                encoded_payload = payload.encode('utf-8')
                            else:
                                encoded_payload = str(payload)
                            
                            sock.sendall(encoded_payload)
                            aprs_queue.task_done()
                            
                        except queue.Empty:
                            break
                        except Exception as e:
                            print("%s 队列数据发送失败: %s" % (ctime(), e))
                            # 发送失败通常意味着连接已断开
                            raise socket.error("Send failed")

                except socket.timeout:
                    # 正常的超时（例如30秒内服务器没发任何包）
                    # 在 APRS 中这很常见，不需要断开连接，继续循环即可
                    continue
                except socket.error as e:
                    print("%s 网络套接字异常: %s" % (ctime(), e))
                    break # 触发重连
                except Exception as e:
                    print("%s 内部通信发生未知异常: %s" % (ctime(), e))
                    break # 触发重连

        except socket.error as e:
            print("%s 无法建立连接 (服务器可能不可用): %s" % (ctime(), e))
        except Exception as e:
            print("%s 客户端运行环境错误: %s" % (ctime(), e))

        finally:
            # 确保资源释放
            if sock:
                try:
                    sock.close()
                except:
                    pass
                print("%s Socket 连接已释放。" % ctime())
            
            # --- 自动重连逻辑 ---
            print("%s %d 秒后将尝试重新连接..." % (ctime(), reconnect_delay))
            sleep(reconnect_delay)

def aprs_tcp_server():
    print("%s Thread ID:%s, name : %s" % (ctime(), hex(threading.current_thread().ident), "aprs_tcp_server"))
    while True :
        sleep(1600)
    
def aprs_udp_server():
    print("%s Thread ID:%s, name : %s" % (ctime(), hex(threading.current_thread().ident), "aprs_udp_server"))
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
                        if ('weather' not in packet_data) and ('latitude' in packet_data):        #只转发有定位的包并且跳过气象包
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
    thread.daemon = True  # 将线程设置为守护线程
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
    check_thread.daemon = True  # 将线程设置为守护线程
    check_thread.start()
    
    # 主线程保持运行
    try:
        while True:
            sleep(10)
    except KeyboardInterrupt:
        print("%s Shutting down..." % ctime())
