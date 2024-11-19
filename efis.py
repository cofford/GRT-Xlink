'''Listens on UDP for the EFIS pings, to setup TCP connections to them

Google Python Style Guide
http://google.github.io/styleguide/pyguide.html#3164-guidelines-derived-from-guidos-recommendations

Use the Queue module’s Queue data type as the preferred way to communicate data between threads. Otherwise, use the threading module and its locking primitives. Learn about the proper use of condition variables so you can use threading.Condition instead of using lower-level locks.
'''

import struct
import socket
import threading
import binascii
import crcmod.predefined        # CRC16.X25
import ctypes
import time
import xplane
import queue
import math

import logging
logging.basicConfig(level=logging.DEBUG,
                    format='(%(threadName)-9s) %(message)s',)



EFIS_PORT = 10001                   # Do not change
MY_LINK_IPADDRESS = 0x10            # We are interlink ID 16 (dec)
#EFIS_IPADDRESS = "192.168.0.1"      # EFIS IPAddress (hardcode, only for debugging to save time)
EFIS_UDP_TIMEOUT = 15               # How long to wait for EFIS to check in

q = queue.Queue()

# Setup class to break out GPS bits from uint32_T
c_uint32 = ctypes.c_uint32   
class DateTimeBits(ctypes.LittleEndianStructure):
    _fields_ = [
        ("month", c_uint32, 4), 
        ("day", c_uint32, 5),
        ("hour", c_uint32, 5),
        ("min", c_uint32, 6),
        ("sec", c_uint32, 6),
        ("status",c_uint32, 1)
    ] 
class GPSDateTimes(ctypes.Union):
    _anonymous_ = ("bit",)
    _fields_ = [
        ("bit", DateTimeBits),
        ("asByte", c_uint32)
    ]

# main
def efis():
    #listen to UDP first, to find all the EFIS out there
    udp_listen()


# Listen on the multicast UDP for EFIS pings (Hello)
def udp_listen():
    '''The UDP hello is a broadcast for units to find each other and establish a TCP connection between each unit. 
    When the UDP broadcasts are exchanged, the unit with the lower IP address of the pair initiates the TCP connection. 
    The EFIS will accept a connection in any order, though. 
    You can skip sending UDP broadcasts and initiate a TCP connection as soon as you see a UDP hello if you do not want to manage 
    accepting TCP connections and sending UDP broadcasts.
    '''

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)       # socket.IPPROTO_UDP
 #   sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind(('', EFIS_PORT))        
    clients = {}
    print(f'Listening on UDP {EFIS_PORT} for Efis pings')
 
    while True:
        # Cheating by setting the ipaddress so we don't have to wait for udp packet
        if not clients and 'EFIS_IPADDRESS' in globals():
            ip = EFIS_IPADDRESS
        else:
            data, addr = sock.recvfrom(1024)
            ip = addr[0]
            
        if ip not in clients:             # Start TCP with new IP address
            send_hello(sock, ip)
            t = threading.Thread(target=tcp_listen(ip))
            t.start() 
            clients[ip] = {}
            clients[ip]['tcp'] = t
            clients_check(ip, 'init')
        else:
            clients_check(addr[0], 'rst')

    sock.shutdown(1)
    sock.close()


# TODO Checks if EFIS clients are still alive, remove if not
def clients_check(ip, task):
    if task == 'rst':
        t = clients[ip]['tmr']
        if t.is_alive():
            #print(f'{ip}: Canceling timer')
            t.cancel()
                   
        task = 'init'   #restart timer
            
    elif task == 'err':
        t = clients[ip]['tcp']
        # TODO - Don't know how to gracefully stop thread
        clients.pop(ip)
        print(f'Removed EFIS: {ip}')

    if task == 'init':
        #print(f'{ip}: Starting timer')
        t = threading.Timer(EFIS_UDP_TIMEOUT, clients_check, args=(ip, 'err'))
        t.setName(ip)
        t.start()
        clients[ip]['tmr'] = t





# Setup main connection to EFIS via TCP
def tcp_listen(ip):

    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    #sock.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
    #sock.setblocking(0)
    sock.connect((ip, EFIS_PORT))

    logging.debug('Found EFIS @ {}'.format(ip))
  
    
    # start a receiving thread
    t = threading.Thread(target=rx_thread,args=(sock,))    
    t.start()

    #look at the Q for a task
    while True:
        try:   
            task, data = q.get_nowait()
            if task=='send':
                send_data(sock, data)         # Send over TCP
            elif task=='hello':
                send_hello(sock)  
            else:
                print(f'Efis: Except task SEND, but got {task}')
            q.task_done()

        except queue.Empty:
            pass
        except Exception as e: 
            print(f'Efis tx loop: {type(e)} = {e}')
            pass
            
    print(f'Efis: Closing down TCP {ip}')
    sock.shutdown(1)
    sock.close()


# Receive payloads
def rx_thread(sock):
    buffer = bytearray()

    while True:
        try:
            buffer.extend(sock.recv(1024))
            for packet in read_buffer(buffer):
                process_packet(packet)

        except BlockingIOError:
            pass
        except Exception as e: 
            print(f'Efis rx loop: {type(e)} = {e}')



# Listen on TCP and decode/verify the packets
def read_buffer(buffer):

    header = -1

    while True:       
        header = buffer.find(b'\x7E')               # Find first instance of Frame flag (could be starting or ending)
                  
        if header >= 0:
            end = buffer.find(b'\x7E',header+1)      # Look for the ending Frameflag, 2 bytes past the start so we know
                                                                # it's the end flag, and not the start of a new packet
            if end >= 2:      
                #print("Feed {}: FrameFlags{}".format(Counters["PacketFeed"], self.tcp_buffer.count(b'\x7E')))
                #print("Org {}".format(binascii.hexlify(self.tcp_buffer)))               

                packet = buffer[header+1:end]           # Grab 1st packet out of buffer and removes frame flags at same time
                del buffer[:end+1]                      # Resize buffer to end of 1st packet
                #print("Packet {}".format(binascii.hexlify(packet)))             
                #print("Remain {}".format(binascii.hexlify(self.tcp_buffer)))  

                packet = packet.replace(b'\x7D\x5E',b'\x7E')        # Stuff Byte (Do this one first)
                packet = packet.replace(b'\x7D\x5D',b'\x7D')        
                msglen = len(packet)
                check_sum = int.from_bytes(packet[msglen-2:msglen], "little")  # last two bytes are checksum, grab the range
                crc16 = crcmod.predefined.Crc('x-25')
                crc16.update(packet[0:msglen-2])
                    
                if check_sum == crc16.crcValue:
                    yield packet[4:msglen-2]        # remove headers and checksum
                else:
                    logging.debug('{} Bad checksum'.format(ip))

            else:
                #print("End Frame flag not found yet")
                break
        else:
            #print("Start Frame flag not found yet")
            break 


# Process the packet
def process_packet(packet):
    """The header has been stripped out of the payload already
    vendorcode = msg[0];       0x5B    vendor protocol code
    scr = msg[1];              0x0A    source ID
    dest = msg[2];             0xFF    broadcast to all
    ttl = msg[3];              0x0A    Time To Live
    """

    type = packet[0]
    payload = packet[1:len(packet)]

    # Hello
    if type == 0x00:           
        #print(f'{self.ip}: Hello ({self.counters["HelloRx"]})')
        # Send Hello back, use their packet as a timer
        q.put(('hello',''))
        
    # State variables
    elif type == 0x02:          
        # print(f'{self.ip}: State variable')
        for var in payload.split(b'\x00'):
            if var:
                var = var.split(b'=')
                state_varibles(int(var[0].decode()), var[1].decode())

    #elif type == 0x07
        #07005C00       #When I cleared the 'Check altitude' message box


    # GPS
    elif type == 0x09:
        subtype = payload[0]
        if subtype== 0x00:           # time, date, position, speed, mag var, from current GPS source, like data in GPRMC
            """Byte 0: Type = 0 (GPS position packet)
            Byte 1: Last two digits of year (year mod 100), zero if unknown
            Byte 2-5: packed LSB first: month (4 bits) | day (5 bits) | hour (5 bits) | min (6 bits) | sec (6 bits) | status (1 bit)
                The date and time fields are all zeroes if unknown.
                The status bit is 1 when the GPS has indicated its data is valid.
                The EFIS may try to use this data as a time source if the day is non-zero and status is 1.
            Byte 6-9: latitude (32-bit float)
            Byte 10-13: longitude (32-bit float)
            Byte 14-15: Ground track in tenths of a degree, MSB first
            Byte 16-17: Magnetic variation in hundredths of a degree, MSB first, positive west
            Byte 18-19: Ground speed in tenths of a knot, MSB first
            Byte 20: bit field
                Bit 0 = GPS2 input is configured on this unit
                Bit 1 = This data is from GPS2
            """
            year = 2000 + payload[1]  
            (var,) = struct.unpack('I', payload[2:6]) 
            datetime = GPSDateTimes()
            datetime.asByte = var
            if datetime.status == 0:
                print("GPS datetime is invalid")  
                
            (latitude,) = struct.unpack('f', payload[6:10])    
            (longitude,) = struct.unpack('f', payload[10:14])
            (ground_track,) = struct.unpack(">H", payload[14:16])    
            ground_track /= 10
            (mag_variation,) = struct.unpack('>h', payload[16:18])
            mag_variation /= 100
            (ground_speed,) = struct.unpack('>H', payload[18:20])
            ground_speed /= 10
    #           msg = "valid:{} = {}-{}-{} {}:{}:{} Lat:{} Long:{} Trk:{} MagVar:{} GS:{}".format(datetime.status, year, datetime.month, datetime.day, datetime.hour, datetime.min, datetime.sec, latitude, longitude, groundTrack, magVariation, groundSpeed)
    #           print(msg)
 
        elif subtype == 0x01:          # navigation data to active waypoint, like data in GPRMB
            """eg1. $GPRMB,A,0.66,L,003,004,4917.24,N,12309.57,W,001.3,052.5,000.5,V*0B
                    A            Data status A = OK, V = warning
                    0.66,L       Cross-track error (nautical miles, 9.9 max.),
                                        steer Left to correct (or R = right)
                    003          Origin waypoint ID
                    004          Destination waypoint ID
                    4917.24,N    Destination waypoint latitude 49 deg. 17.24 min. N
                    12309.57,W   Destination waypoint longitude 123 deg. 09.57 min. W
                    001.3        Range to destination, nautical miles
                    052.5        True bearing to destination
                    000.5        Velocity towards destination, knots
                    V            Arrival alarm  A = arrived, V = not arrived
                    *0B          mandatory checksum
            """
            print(binascii.hexlify(payload)) 
            print(binascii.hexlify(payload[1:3]),end='')
            (dest_latitude,) = struct.unpack('f', payload[3:7])    
            (dest_longitude,) = struct.unpack('f', payload[7:11])
            (orig_latitude,) = struct.unpack('f', payload[11:15])    
            (orig_longitude,) = struct.unpack('f', payload[15:19])
            (true_bearing,) = struct.unpack('>H', payload[19:21])    # 3 degree higher then on efis
            (destination_range,) = struct.unpack('>H', payload[21:23])   # in nM    why2
            print(binascii.hexlify(payload[23:29]))
            #payload[24]
            #payload[25]
            #payload[26]
            #payload[27]
            #payload[28]
            (destination_range2,) = struct.unpack('>H', payload[29:31])   #in nM   why2
            destination_waypoint = payload[31:]    #ascii     
            destination_range /= 10

        elif subtype == 0x02:          # waypoints in active flight plan from current GPS source
            print(binascii.hexlify(payload))  

        elif subtype == 0x03:          # time and date from GPS1 and/or GPS2 independent of current GPS source
            """Byte 0: 03 = time/date
            Byte 1: GPS Source (pretty sure)
            Byte 2: Last two digits of year (year mod 100), zero if unknown
            Byte 3-6: packed LSB first: month (4 bits) | day (5 bits) | hour (5 bits) | min (6 bits) | sec (6 bits) | status (1 bit)
            """
            year = 2000 + payload[2]  
            (var,) = struct.unpack('I', payload[3:7]) 
            datetime = GPSDateTimes()
            datetime.asByte = var
            if datetime.status:
                msg = "Gps: valid:{} = {}-{}-{} {}:{}:{}".format(datetime.status, year, datetime.month, datetime.day, datetime.hour, datetime.min, datetime.sec)
    #               print(msg)
            else:
                print("GPS datetime is invalid")

        elif subtype == 0x04:           # GPS altitude and geoidal difference, fix quality, number of satellites used, from current GPS source, like data in GPGGA   */        //Gps position packet
            gps_mode = payload[1]            # Gps Mode      3 = Auto Fix 3D
            gps_source = payload[2]          # Gps source
            sats_in_calculation = payload[3]  # SatInCalculation 
            (gps_altitude,) = struct.unpack('f', payload[4:8])    
            gps_altitude = round(gps_altitude*3.281,1)      # convert meters to ft
            (geoidal,) = struct.unpack('f', payload[8:12])       

            msg = "gpsMode:{} gpsSource:{} satsInCalculation:{} gpsAltitude:{} geoidal:{}".format(gps_mode, gps_source, sats_in_calculation, gps_altitude, geoidal)
      
#    elif type == 0x10:      # 0x10  Flight plan
#        return                                   
       
    elif type == 0x1A:      # 0x1A  Nav/Com state packet. volume levels, audiopanel modes, transponder modes, drive boxes upper right hand corner
        return                       
    else:
        print('Packet {} not setup for processing yet'.format(type))
        print(binascii.hexlify(packet))  


# EFIS expects a ping (Hello) every 10 seconds
def send_hello(sock, ip = False):
    payload = bytearray()
    payload.append(0x00)                # packet type 00 = Hello
    payload.append(0x01)                # link version 
    payload.extend((0x00, 0x00))        # display serial number

    send_data(sock, payload, ip)         # Send over TCP

   
# Pack payload with header and checksum, send to EFIS
def send_data(sock, payload, ip = False):
    packet = bytearray()
    packet.append(0x5B)                 # vendor protocol code
    packet.append(MY_LINK_IPADDRESS)    # source ID
    packet.append(0xFF)                 # broadcast to all IPs
    packet.append(0x0A)                 # Time To Live 
    packet.extend(payload)
    
    # Add Checksum crc16.x25
    crc16 = crcmod.predefined.Crc('x-25')
    crc16.update(packet)
    packet.extend(crc16.crcValue.to_bytes(2, 'little'))         

    packet = packet.replace(b'\x7D',b'\x7D\x5D')        # Stuff Byte (Do this first)
    packet = packet.replace(b'\x7E',b'\x7D\x5E')        

    if ip:
        try:
            #for ip in obj.clients.keys():
            sock.sendto(packet, (ip, EFIS_PORT))
        except:
            print('Error sending UDP data to EFIS')

    else:
        # TCP needs FrameFlags where UDP does not
        packet.insert(0, 0x7E)
        packet.append(0x7E)
        try: 
            sock.sendall(packet)
        except:
            print(f'{ip}: Error sending TCP data to EFIS')


#Saving the EFIS state varibles, relaying over to X-plane
def state_varibles(index, value):
    """
    3 = Select Heading bug            NOT SURE  divide by 0.0174532924791086 to get degree
    4 = Selected Altitude
    6 =
    7 = AUTO=1 3 VS=4 3  ASPD=3 4    VNav=
    12 = Baro          Not sure what last two digits are
    13 = Climb IAS  (Auto mode, also changed #30)
    14 = VRate
    18 = Screen dim  (255,128,64,32,16,8,4,2,1,0)
    25 = LAT A/p   0=ENav, 1=Hdg, =GNav (need gps with roll steering)
    30 = Climb and descent on a selected IAS airspeed (ASPD mode)
    31 = Climb and descent on vertical Speed Rate (VS mode)
    35 = DA = Decision Altitude
    36 = Missed App Altitude
    37 = Preset Altitude
    49 = (Comes with #25) 
    93 = SAP
    """
    value = string_to_number(value)
    if index == 3: 
        value = round(float(value) / 0.0174532924791086)    #convert from efis degrees
    
    elif index == 25:
        index = index + (value/10)

    elif index == 35 or index == 36 or index == 37:
        if value == -2147483648:    #clear value
            value = ""
        return

    xplane.efis_updating(index, value)


def string_to_number(str):
    if("." in str):
        try:
            res = float(str)
        except:
            res = str  
    elif(str.isdigit()):
        res = int(str)
    else:
        res = str
    return(res)


# Sync Xplane data with Efis state variables
def update_statevariable(index, value):

    if index == 3:      # Select Heading bug
        value = value * 0.0174532924791086    #convert to efis degrees
    
    elif index >= 25 and index <= 25.9:
        if value == 2:  #we only care what is set, dismiss the other changes
            frac, whole = math.modf(index)
            index = int(whole)
            value = int(round(frac,1) * 10)
            if value == 2:  # we don't have GPS Steer
                value = 0

        else:
            return

    payload = bytearray()
    payload.append(0x02)        # packet type
    payload.extend(str(index).encode())  
    payload.append(0x3D)        #  = 
    payload.extend(str(value).encode())  
    payload.append(0x00)        #  null 
    
    q.put(('send', payload))


