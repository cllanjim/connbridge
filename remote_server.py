from twisted.internet.protocol import Protocol,Factory
from twisted.protocols import basic
from cbprotocol import CBServerFactory
import sys
from twisted.python import log

PORT = 8586

def main():
	from twisted.internet import reactor
	f = CBServerFactory()
	reactor.listenTCP(PORT, f)
	reactor.run()

if __name__ == '__main__':
	log.startLogging(sys.stdout)
	main()