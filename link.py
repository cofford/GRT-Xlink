import struct
import serial
import xplane
import efis
from time import sleep
import socket
import threading
import datetime
import ctypes
import binascii

#Setup class to break out GPS bits from uint32_T
c_uint32 = ctypes.c_uint32   
class DateTime_bits( ctypes.LittleEndianStructure ):
    _fields_ = [
        ("month", c_uint32, 4 ), 
        ("day",   c_uint32, 5 ),
        ("hour",  c_uint32, 5 ),
        ("min",   c_uint32, 6 ),
        ("sec",   c_uint32, 6 ),
        ("status", c_uint32, 1 )
    ] 
class GPSDateTimes( ctypes.Union ):
    _anonymous_ = ("bit",)
    _fields_ = [
        ("bit",    DateTime_bits ),
        ("asByte", c_uint32    )
    ]


# main
def link(ipaddresses, port):

    #TODO conitnue only when xplane and efis are connected

    for ip in ipaddresses:
        t = threading.Thread(target=ahrs, args=[ip, port])
        t.start()

    payloads = ['gps0', 'gps3', 'gps4', 'eis']
    while True:
        for p in payloads:
            efis.q.put(('send', globals()[p]()))  
            sleep(0.1)


#Load payload of AHRS data
def ahrs_data(task):       
    if task == 'high':
        header = b'\x7f\xff'
        identifier = b'\xfe\x00' 
      
        scalefactor = 32767 / 180  #scale factor for pitch, roll, yaw
        scaled_roll = int (xplane.get_value('roll') * scalefactor)
        scaled_yaw = int (xplane.get_value('heading_mag') * scalefactor)
        #print(yaw)
        #print(scaled_yaw)
        scaled_pitch = int (xplane.get_value('pitch') * scalefactor)
        scaled_alt = int (xplane.get_value('asl') * 3.28084 + 5000)    # Unsigned value with 5000’ offset (meters to ft)
        #print(altitude)
        #print(scaled_alt)
        scaled_vspeed = int (xplane.get_value('v_speed') * 196.85)      # m/s to ft/min
        scaled_vind = int (xplane.get_value('ias') * 1.68781 * 10)      # kt to 0.1 ft/sc

        airspeed_rate = 0
        accel_roll_rate = 0
        accel_normal_rate = 0
    

        payload = struct.pack('>2s2shhHHhhhhh', header, identifier, scaled_roll, scaled_pitch, scaled_yaw, scaled_alt, scaled_vspeed, scaled_vind, airspeed_rate, accel_roll_rate, accel_normal_rate)
    

    else:       # lowrate
        payload = b'\x7f\xff\xfd\x00\x05\xa1\x05\xa2\x05\xa3\x00\x00\x00\x64\x00\x2b\x00\x00\x00\x00'
        
    checksum = ((sum(payload[2:])) & 0xFF) ^ 0XFF
    checksum = struct.pack('B', checksum)

    return (payload + checksum)


# AHRS data to serial port
def ahrs(ip, port):
    sleep(2)
    index = 0
    connect = False
    sock =  socket.socket(socket.AF_INET,socket.SOCK_STREAM)
    sock.getsockopt(socket.SOL_SOCKET,socket.SO_REUSEADDR) 
    
    try:
        sock.connect((ip, port))
        connect = True
    except:
        print(f'Can not connect to VM @ {ip}')

    while connect:
        #TODO only do this is xplane has data
        if (xplane.get_value('roll')):
            if index < 15:
                packet = ahrs_data('high')
        
            if index == 15:
                packet = ahrs_data('low')
                index = -1   

            try:
                sock.send(packet)
                index += 1
                sleep(0.05)
            except Exception as e: 
                print(f'Link ahrs: {type(e)} = {e}')
                pass

    print(f'Closing hxr_Serial {ip}')
    sock.close()



# GPS GPRMC
def gps0(): 
    # time, date, position, speed, mag var, from current GPS source, like data in GPRMC
    payload = bytearray()
    payload.append(0x09)        #Packet Type
    
    timeNow = datetime.datetime.now()
    year = str(timeNow.year)
    year = int(year[2:])
    timeBits = GPSDateTimes()
    timeBits.bit.month = timeNow.month
    timeBits.bit.day = timeNow.day
    timeBits.bit.hour = timeNow.hour
    timeBits.bit.min = timeNow.minute
    timeBits.bit.sec = timeNow.second
    timeBits.bit.status = 1

    track = int(xplane.get_value('heading_actual')*10)
    magvar = int(xplane.get_value('mag_var')*100) 
    gndspeed = int(xplane.get_value('gnd_speed')*10*1.94384)
    bits = 0

    payload.append(0x00)                     #Byte 0: 00 = GPS position packet
    payload.append(year)                     #Byte 1: Last two digits of year (year mod 100), zero if unknown
    payload.extend(struct.pack('I', timeBits.asByte))          #Byte 2-5: packed LSB first: month (4 bits) | day (5 bits) | hour (5 bits) | min (6 bits) | sec (6 bits) | status (1 bit)
                                                #The date and time fields are all zeroes if unknown.
                                                #The status bit is 1 when the GPS has indicated its data is valid.
                                                #The EFIS may try to use this data as a time source if the day is non-zero and status is 1.
    payload.extend(struct.pack('ff', xplane.get_value('latitude'), xplane.get_value('longitude')))   #Byte 6-9: latitude (32-bit float)
                                                                    #Byte 10-13: longitude (32-bit float)
    payload.extend(struct.pack(">HhHb", track, magvar, gndspeed, bits))  #Byte 14-15: Ground track in tenths of a degree, MSB first
                                                                    #Byte 16-17: Magnetic variation in hundredths of a degree, MSB first, positive west
                                                                    #Byte 18-19: Ground speed in tenths of a knot, MSB first
                                                                    #Byte 20: bit field
                                                                        #Bit 0 = GPS2 input is configured on this unit
                                                                        #Bit 1 = This data is from GPS2
    return payload


# GPS Time
def gps3():
    # time and date from GPS1 and/or GPS2 independent of current GPS source
    payload = bytearray()
    payload.append(0x09)        #Packet Type
    
    timeNow = datetime.datetime.now()
    year = str(timeNow.year)
    year = int(year[2:])
    timeBits = GPSDateTimes()
    timeBits.bit.month = timeNow.month
    timeBits.bit.day = timeNow.day
    timeBits.bit.hour = timeNow.hour
    timeBits.bit.min = timeNow.minute
    timeBits.bit.sec = timeNow.second
    timeBits.bit.status = 1

    payload.append(0x03)                #Byte 0: 03 = time/date
    payload.append(0x00)                #Byte 1: GPS Source (pretty sure)
    payload.append(year)                #Byte 2: Last two digits of year (year mod 100), zero if unknown
    payload.extend(struct.pack('I', timeBits.asByte))          #Byte 3-6: packed LSB first: month (4 bits) | day (5 bits) | hour (5 bits) | min (6 bits) | sec (6 bits) | status (1 bit)
                                                #The date and time fields are all zeroes if unknown.
                                                #The status bit is 1 when the GPS has indicated its data is valid.
                                                #The EFIS may try to use this data as a time source if the day is non-zero and status is 1.
    return payload


# GPS GPGGA
def gps4():
    # GPS altitude and geoidal difference, fix quality, number of satellites used, from current GPS source, like data in GPGGA   */        //Gps position packet
    payload = bytearray()
    payload.append(0x09)        #Packet Type

    gpsAltitude = int(xplane.get_value('asl'))   #in meters
    geoidal = 0

    payload.append(0x04)    
    payload.append(0x03)        #Gps Mode      3 = Auto Fix 3D
    payload.append(0x00)        #Gps source
    payload.append(0x05)        #SatInCalculation 
    payload.extend(struct.pack('ff', gpsAltitude, geoidal))    

    return payload


# Engine data to EFIS interlink
def eis():
    payload = bytearray()
    payload.append(0x0F)            #Packet Type = EIS1 0x0F    EIS2 0x27
    
    #convert and scale variables
    cht = [0] * 6
    egt = [0] * 9
    aux = [0] * 6

    rpm = int(xplane.get_value('rpm'))
    if rpm < 0:
        rpm = 0
    cht[0:4] = (int(xplane.get_value('cht')),) * 4    #wrap scalar in an iterable
    egt[0:4] = (int(xplane.get_value('egt')),) * 4
    airspeed = 0        #not displayed in EFIS
    altimeter = 0       #not displayed in EFIS
    volts = float(xplane.get_value('volts'))
    fuelflow = float(xplane.get_value('fuelflow') * 1286.33)      #convert kg_sec to gal_hour xx.x
    internaltemp = 0        #Don't think is used in EFIS
    manifoldtemp = -100        #aka carb temperature
    verticalspeed = 0       #Not sure if used in EFIS
    oat = int(xplane.get_value('oat'))
    oiltemp = int(xplane.get_value('oiltemp'))
    oilpressure = int(xplane.get_value('oilpressure'))
    aux[0] = int(xplane.get_value('manifoldpressure') * 10)
    aux[1] = int(xplane.get_value('fuelpressure') * 10)
    aux[2] = 0
    aux[3] = 0
    aux[4] = 0
    aux[5] = 0
    coolanttemp = 0
    hobbs = float(xplane.get_value('hobbs') / 3600)
    fuelqty = float((xplane.get_value('fuel_qty_left') + xplane.get_value('fuel_qty_right')) / 2.72155)         #gallon is 2.72155kg (6lbs)
    flight_hrs = (int(xplane.get_value('flighttime') / 3600))         #HH:MM:SS
    flight_min = (int((xplane.get_value('flighttime') % 3600) / 60))
    flight_sec = (int((xplane.get_value('flighttime') % 3600) % 60))
    fuelflowtime = 0                        #Fuel Flow Time until empty HH:MM
    baropressure = float(xplane.get_value('baropressure'))       #Not sure if being used
    savebit = 0                 #The bits are set when we see 10 zero values in a row
                                #Bit0 = tachometer has stopped (steady at zero)   
                                #Bit1 = fuel flow has stopped (steady at zero)
                                #Bit2 = additional data follows for a CAN bus input
    rpm2 = 0
    eisver = 59             #0x00 0x3B

    payload.extend(struct.pack(">H6H9HH", rpm, cht[0], cht[1], cht[2], cht[3], cht[4], cht[5], egt[0], egt[1], egt[2], egt[3], egt[4], egt[5], egt[6], egt[7], egt[8], airspeed))
    payload.extend(struct.pack("<fff", altimeter, volts, fuelflow))
    payload.extend(struct.pack(">bbfhHB", internaltemp, manifoldtemp, verticalspeed, oat, oiltemp, oilpressure))
    payload.extend(struct.pack(">hhhhhhH", aux[0], aux[1], aux[2], aux[3], aux[4], aux[5], coolanttemp))
    payload.extend(struct.pack("<ff", hobbs, fuelqty))
    payload.extend(struct.pack(">BBBH", flight_hrs, flight_min, flight_sec, fuelflowtime))
    payload.extend(struct.pack("<f", baropressure))
    payload.extend(struct.pack(">BHH", savebit, rpm2, eisver))

 #   print(binascii.hexlify(payload))

    return payload





 


if __name__ == "__main__":
    link()
    

    