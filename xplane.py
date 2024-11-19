import socket
import struct 
import threading
import queue
import efis
import datetime

q = queue.Queue()

BEACON_IP = '239.255.1.1'   # Xplane beacon multicast group
BEACON_PORT = 49707

XPLANE_MAJOR_VER = 1        # This python code is designed for this xplane UDP version
XPLANE_MINOR_VER = 2

my_data = {}
def store_refs(name, efis=0, ref='', freq=0, perc=-1, cmd=''):
    # name = variable name
    # efis = index of EFIS state variables
    # ref = string of Xplane data reference
    # freq = how many times a second to get data from xplane
    # value = holds the value of variable
    # perc = precision of the decimal place
    # lock = holds time to block xplane re-updating value after efis has just updated it
    # cmd = variable could be a command for EFIS to run on xplane
    
    if my_data.get(name, None) is None:
        var = {'efis':efis, 'ref':ref, 'freq':freq, 'value':0, 'perc':perc, 'lock':datetime.datetime.now(), 'cmd':cmd}
        my_data.update({name : var})
    else:
        raise IndexError(f'Xplane store_refs: {name} is already in my_data') 


# RPOS data
store_refs('longitude', 0, 'sim/flightmodel/position/longitude', 20)    
store_refs('latitude', 0, 'sim/flightmodel/position/latitude', 20)      
store_refs('asl', 0, 'sim/flightmodel/position/elevation', 20)          #elevation above sea level in meters
store_refs('agl', 0, 'sim/flightmodel/position/y_agl', 20)              #elevation above terrain in meters
store_refs('pitch', 0, 'sim/cockpit2/gauges/indicators/pitch_AHARS_deg_pilot', 20)      #pitch in degrees
store_refs('heading_true', 0, 'sim/flightmodel/position/true_psi', 20)  #heading relative to the earth precisely below the aircraft, true degrees north
store_refs('roll', 0, 'sim/flightmodel/position/true_phi', 20)          #roll in degrees
store_refs('x_speed', 0, 'sim/flightmodel/position/local_vx', 20)       #speed in EAST, m/s
store_refs('v_speed', 0, 'sim/flightmodel/position/local_vy', 20)       #speed in UP, m/s
store_refs('z_speed', 0, 'sim/flightmodel/position/local_vz', 20)       #speed in SOUTH, m/s
store_refs('p_rad', 0, 'sim/flightmodel/position/Prad', 20)         #roll rate in radians/s
store_refs('q_rad', 0, 'sim/flightmodel/position/Qrad', 20)         #pitch rate in radians/s
store_refs('r_rad', 0, 'sim/flightmodel/position/Rrad', 20)         #yah rate in radians/s

# user data
store_refs('heading_bug', 3, 'sim/cockpit/autopilot/heading_mag', 2, 0)
store_refs('baropressure', 12, 'sim/cockpit2/gauges/actuators/barometer_setting_in_hg_pilot', 3, 2)
store_refs('mag_var', 0, 'sim/flightmodel/position/magnetic_variation', 20)     # The local magnetic variation
store_refs('heading_mag', 0, 'sim/flightmodel/position/mag_psi', 20)          # "°", "The real magnetic heading of the aircraft
store_refs('heading_gnd', 0, 'sim/cockpit2/gauges/indicators/ground_track_mag_pilot', 20)      # The ground track of the aircraft in degrees magnetic
store_refs('heading_actual', 0, 'sim/flightmodel/position/hpath', 20)       # The heading the aircraft actually flies. (hpath+beta=psi)
store_refs('ias', 0, 'sim/flightmodel/position/indicated_airspeed', 20)     # "kt", "Air speed indicated - this takes into account air density and wind direction
store_refs('gnd_speed', 0, 'sim/flightmodel/position/groundspeed', 20)            # "m/s", "The ground speed of the aircraft
store_refs('rpm', 0, 'sim/cockpit2/engine/indicators/engine_speed_rpm[0]', 20)
store_refs('cht', 0, 'sim/cockpit2/engine/indicators/CHT_deg_C[0]', 20)
store_refs('egt', 0, 'sim/cockpit2/engine/indicators/EGT_deg_C[0]', 20)
store_refs('fuelflow', 0, 'sim/cockpit2/engine/indicators/fuel_flow_kg_sec[0]', 20)
store_refs('fuelpressure', 0, 'sim/cockpit2/engine/indicators/fuel_pressure_psi[0]', 20)
store_refs('oilpressure', 0, 'sim/cockpit2/engine/indicators/oil_pressure_psi[0]', 20)
store_refs('oiltemp', 0, 'sim/cockpit2/engine/indicators/oil_temperature_deg_C[0]', 20)
store_refs('manifoldpressure', 0, 'sim/cockpit2/engine/indicators/MPR_in_hg[0]', 20)
store_refs('manifoldtemp', 0, 'sim/cockpit2/engine/indicators/carburetor_temperature_C[0]', 20)
store_refs('oat', 0, 'sim/cockpit2/temperature/outside_air_temp_degf[0]', 20)
store_refs('hobbs', 0, 'sim/time/hobbs_time', 20)     # seconds
store_refs('flighttime', 0, 'sim/time/total_flight_time_sec', 20)
store_refs('volts', 0, 'sim/flightmodel/engine/ENGN_bat_volt[0]', 20)
store_refs('fuel_qty_left', 0, 'sim/cockpit2/fuel/fuel_level_indicated_left', 20)     # in lbs
store_refs('fuel_qty_right', 0, 'sim/cockpit2/fuel/fuel_level_indicated_right', 20)    # in lbs

store_refs('ap_enav', 25.0, 'sim/cockpit2/autopilot/nav_status', 2, cmd='sim/autopilot/NAV')
store_refs('ap_heading', 25.1, 'sim/cockpit2/autopilot/heading_status', 2, cmd='sim/autopilot/heading')   
store_refs('ap_gnav', 25.2, 'sim/cockpit2/autopilot/gpss_status', 2, cmd='sim/autopilot/NAV')
store_refs('ap_altitude', 4, 'sim/cockpit/autopilot/current_altitude', 2)


store_refs('com1_freq', 0, 'sim/cockpit2/radios/actuators/com1_frequency_hz', 2)




# main loop
def xplane():

    beacon = find_beacon()
    port = beacon['port']
    print(f'Xplane: Starting UDP connection with Xplane on port {port}')
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM) 
#    sock.bind(('', port))   

    cmd = b"RPOS\x00"
    freq=b"20\x00"
    message = struct.pack("<5s2s", cmd, freq)
    sock.sendto(message, (beacon['ip'], beacon['port']))


    load_refs(sock, beacon)     #load data to receive

    # start a receiving thread
    t = threading.Thread(target=rx_thread,args=(sock,))    
    t.start()

    # look at the Q for a task
    while True:
        try:
            task, data = q.get()
            if task=='send':
                sock.sendto(data, (beacon['ip'], beacon['port']))
            else:
                print(f'Xplane: Except task SEND, but got {task}')
            q.task_done()
        except queue.Empty:
            pass
        except Exception as e: 
            print(f'Xplane tx loop: {type(e)} = {e}')
            pass

 
    print(f'XPlane: Closing down UDP {port}')
    sock.shutdown(1)
    sock.close()

                   
# Mass loading data refs from xplane    
def load_refs(sock, beacon):
    for index, (key, value) in enumerate(my_data.items()):
        # Send one RREF Command for every dataref in the list.
        # Give them an index number and a frequency in Hz.
        # To disable sending you send frequency 0. 
        cmd = b'RREF\x00'
        freq = value['freq']
        string = value['ref'].encode()
        message = struct.pack('<5sii400s', cmd, freq, index, string)
        assert(len(message)==413)
        sock.sendto(message, (beacon['ip'], beacon['port']))
 
        
# Listen for multicast beacon to find Xplane master
def find_beacon():

    print(f'Listening for Xplane beacon on UDP {BEACON_IP}:{BEACON_PORT}')
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind(('', BEACON_PORT))  
    req = struct.pack("=4sl", socket.inet_aton(BEACON_IP), socket.INADDR_ANY)
    sock.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, req)

    beacon = {}
    while not beacon:
        packet, sender = sock.recvfrom(1024)
        if packet[0:5] == b'BECN\x00':
            # struct becn_struct
            # {
            # 	uchar beacon_major_version;		// 1 at the time of X-Plane 10.40
            # 	uchar beacon_minor_version;		// 1 at the time of X-Plane 10.40
            # 	xint application_host_id;			// 1 for X-Plane, 2 for PlaneMaker
            # 	xint version_number;			// 104014 for X-Plane 10.40b14
            # 	uint role;						// 1 for master, 2 for extern visual, 3 for IOS
            # 	ushort port;					// port number X-Plane is listening on
            # 	xchr	computer_name[strDIM];		// the hostname of the computer 
            # };
            data = packet[5:21]
            (   
                beacon_major_version, 
                beacon_minor_version, 
                application_host_id, 
                xplane_version_number, 
                role, 
                port,
            )= struct.unpack('<BBiiIH', data)
            xplane_version_number = str(xplane_version_number)
            computer_name = packet[21:-2].decode()
            if beacon_major_version == XPLANE_MAJOR_VER \
                and beacon_minor_version == XPLANE_MINOR_VER \
                and application_host_id == 1 \
                and role == 1:

                print(f'Found Xplane {xplane_version_number[0:2]}.{xplane_version_number[2:4]}b{xplane_version_number[4:6]} running on {computer_name} ({sender[0]}:{port})')                            
                beacon['ip'] = sender[0]
                beacon['port'] = port

    #sock.shutdown(1)
    sock.close()
    return beacon


# loop for receiving data
def rx_thread(sock):

    index_keys = list(my_data) 

    while True:
       # Receive packet
        try:
            packet, addr = sock.recvfrom(1024) # buffer size is 1024 bytes
            values = decode_packet(packet)     # Decode Packet
            
            if packet[0:5]==b'RREF,':
                for key,value in values.items():
                    data = my_data[index_keys[key]]
                    if data['perc'] == 0:
                        value = int(value)
                    elif data['perc'] > 0:
                        value = round(value, data['perc'])

                    if key==999:                # temporary one-off key
                        q.put(('value', value))
                    
                    elif data['value'] != value:     # update if values don't match
                        
                        if datetime.datetime.now() >= data['lock']:   # there is no lock from EFIS
                            xplane_updating(index_keys[key], value)

        except socket.timeout:
            pass        
        except socket.error:
            #If no data is received, you get here, but it's not an error
            pass
        except Exception as e: 
            print(f'Xplane rx_thread: {type(e)} = {e}')


# decode packets received from xplane
def decode_packet(data):
    retvalues = {}

    if data[0:5]==b"RPOS4":
        retvalues = struct.unpack("<5sdddffffffffff", data)
        #print(f'{retvalues[6]}')

    elif data[0:5]==b'RREF,':
        # We get 8 bytes for every dataref sent:
        #    An integer for idx and the float value. 
        values = data[5:]
        lenvalue = 8
        numvalues = int(len(values)/lenvalue)
        idx=0
        value=0
        for i in range(0,numvalues):
            singledata = data[(5+lenvalue*i):(5+lenvalue*(i+1))]
            (idx,value) = struct.unpack('<if', singledata)
            #retvalues[idx] = (value, datarefs[idx][1], datarefs[idx][0])
            retvalues[idx] = value

    else:
        print(f'Xplane decode_packet: Unknown packet {data}')
  
    return retvalues


# Gets a ref, only once 
def get_ref(ref):
    cmd = b"RREF\x00"      
    freq = 20
    index = 999
    string = ref.encode()
    message = struct.pack("<5sii400s", cmd, freq, index, string)
    assert(len(message)==413)
    q.put(('send', message))
#        sock.sendto(message, (UDP_IP, UDP_PORT))
        
    q.join()
    # wait here for the result to be available before continuing
    result = ''
    task, data = q.get()
    if task=='value':
        result = data
    else:
        print(f'Xplane get_ref: Except task VALUE, but got {task}')

    q.done()
#     result_available.wait()
#     result_available.clear()
    
    freq = 0    # set freq to zero, only need the data once
    message = struct.pack("<5sii400s", cmd, freq, index, string)
    assert(len(message)==413)
    q.put(('send', message))
#        sock.sendto(message, (UDP_IP, UDP_PORT))
        
    return result


def send_cmd(value):
    cmd = b"CMND\x00"      
    string = value.encode()
    message = struct.pack("<5s", cmd) + string
   # assert(len(message)==413)
    q.put(('send', message))


# EFIS has new data to sync
def efis_updating(key, value):
    message = ''
    
    hit = False
    if isinstance(key, int):       #state variable numeric key
        for data in my_data.values():
            if data['efis'] == key:    # efis has match in my_data
                hit = True
    else:
        if key in my_data:
            data = my_data.get(key)
            hit = True

    if hit:        
        if len(data['cmd']) != 0:     #run command 
            cmd = b"CMND\x00"      
            string = data['cmd'].encode()
            message = struct.pack("<5s", cmd) + string
            print(message)

        else:
            old = data['value']
            perc = data['perc']
            if data['perc'] == 0:
                value = int(value)
            elif data['perc'] > 0:
                value = round(value, perc)
            data['value'] = value

            #delay xplane from re-updating until it can catch up to the changes 
            data['lock'] = datetime.datetime.now() + datetime.timedelta(seconds=1)               

            cmd = b'DREF\x00'
            ref = data['ref'].encode()
            message = struct.pack('<5sf500s', cmd, value, ref)
            assert(len(message)==509)           
                
        q.put(('send', message))

    else:
        print("Xplane efis_updating: Efis varible key '{}' has no match to my_data. Value = {}".format(key, value))
    


# Xplane has new data to sync
def xplane_updating(name, value):
    old = my_data[name]['value']
    perc = my_data[name]['perc']
    if perc >= 0:
        value = round(value, perc)

    my_data[name]['value'] = value
    
    #Only update the EFIS is there is a link to a statevariable  
    if my_data[name]['efis'] > 0: 
        efis.update_statevariable(my_data[name]['efis'], value)       
        #print(f'Xplane xplane_updating: updated {name} = {old} to {value}')

    return
  
            
#return value using the name in the dictionary         
def get_value(name):
    val = my_data.get(name)
    if val is not None:
        return val['value']
    else:
        raise IndexError(f'Xplane: {name} not found in Xplane Refs') 

   
#search dictionary for index, return the key        
def get_nth_key(dictionary, n=0):
    if n < 0:
        n += len(dictionary)
    for i, key in enumerate(dictionary.keys()):
        if i == n:
            return key
    raise IndexError("Xplane: Dictionary index out of range") 

    

    

if __name__ == '__main__':
  xplane()
