# You can run this .tac file directly with:
#    twistd -ny service.tac

"""
This is an example .tac file which starts a webserver on port 8080 and
serves files from the current working directory.

The important part of this, the part that makes it a .tac file, is
the final root-level section, which sets up the object called 'application'
which twistd will look for
"""

import os
from twisted.application import service, internet
from twisted.web import static, server
import remote_server, wpprotocol

application = service.Application("wallproxy remote server")
service = internet.TCPServer(remote_server.PORT, wpprotocol.WPServerFactory())
service.setServiceParent(application)