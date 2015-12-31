from twisted.internet.protocol import Protocol,Factory
from twisted.protocols import basic
from wpprotocol import WPServerFactory
import sys
from twisted.python import log

from wpprotocol_generator import gen_protocol_if_needed

PORT = 8586

def main():
	gen_protocol_if_needed()
	from twisted.internet import reactor
	f = WPServerFactory()
	reactor.listenTCP(PORT, f)
	reactor.run()

if __name__ == '__main__':
	log.startLogging(sys.stdout)
	main()