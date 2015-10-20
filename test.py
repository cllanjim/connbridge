
from twisted.internet.endpoints import TCP4ClientEndpoint
from twisted.internet import protocol

class TestProtocol(protocol.Protocol):
	def connectionMade(self):
		print 'made'
		self.transport.loseConnection()
		#raise Exception()

	def connectionLost(self, reason):
		print 'lost'

from twisted.internet import reactor

#e = TCP4ClientEndpoint(reactor, "www.baidu.com", 80)
e = TCP4ClientEndpoint(reactor, "192.168.64.131", 8080)
f = protocol.Factory()
f.protocol = TestProtocol
e.connect(f)
reactor.run()