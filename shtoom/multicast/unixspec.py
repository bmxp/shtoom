#
#
# Copyright (c) 2004 Anthony Baxter.
#

from socket import *

def leaveGroup(sock,addr):
    """Join a multicast group. 
       arguments:
       sock = an already open socket.
       addr = either a string, which will be passed to gethostbyname(), or
       a 32 bit number (the string can be a DNS name, or a dotted quad.
"""
    mreq = _addr2mreq(addr)
    # And join the group .
    sock.setsockopt(IPPROTO_IP, IP_DROP_MEMBERSHIP, mreq)

def _addr2mreq(addr):
    import netnum,struct
    from socket import *

    if type(addr) is type(""):
	group = gethostbyname(addr)
	grpaddr = netnum.dq2num(group)
    else:
	grpaddr = addr
    mreq = struct.pack('ll', grpaddr, INADDR_ANY)
    return mreq

def joinGroup(sock,addr):
    """Join a multicast group. 
       arguments:
       sock = an already open socket.
       addr = either a string, which will be passed to gethostbyname(), or
       a 32 bit number (the string can be a DNS name, or a dotted quad.
"""
    mreq = _addr2mreq(addr)
    sock.setsockopt(IPPROTO_IP, IP_ADD_MEMBERSHIP, mreq)


