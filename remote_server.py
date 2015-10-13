from twisted.internet.protocol import Protocol,Factory
from twisted.protocols import basic
from wpprotocol import WPServerFactory
import sys
from twisted.python import log

PORT = 8586

def main():
	from twisted.internet import reactor
	f = WPServerFactory()
	reactor.listenTCP(PORT, f)
	reactor.run()

if __name__ == '__main__':
	log.startLogging(sys.stdout)
	main()