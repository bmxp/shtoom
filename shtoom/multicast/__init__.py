#
#
# Copyright (c) 2004 Anthony Baxter.
#

import socket
if "IP_ADD_MEMBERSHIP" in socket.__dict__:
    from .unixspec import joinGroup,leaveGroup
else:
    raise ImportError("Don't know how to support multicast on this system")

def ntp2delta(ticks):
    return (ticks - 220898800)
