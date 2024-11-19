from threading import Thread
from xplane import xplane, efis_updating
from efis import efis
from link import link


VM_IP = {'127.0.0.1', '192.168.0.1'}    #hardcoded IP address of VM boxes to send AHRS over TCP
VM_PORT = 12345

#Listen for beacon and start UDP link to XPlane
t = Thread(target=xplane)
t.start()

#Listens for EFIS's over UDP then setups up direct connection via TCP
t = Thread(target=efis)
t.start() 

#TCP data to EFIS's virtual serial ports, (packets that aren't in the interlink) 
t = Thread(target=link(VM_IP, VM_PORT))
t.start()


#g = input("Enter your name : ") 
#if g == '1':
#    efis_updating('com1_freq', 12344)