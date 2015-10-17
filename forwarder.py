from twisted.internet.protocol import ClientFactory, Protocol
from twisted.internet import defer
from twisted.python import log

class BiMap:
	[FORWADER, ID] = range(1,3)
	def __init__(self):
		self._forwarder2id = {}
		self._id2forwarder = {}
	def add(self, forwarder, id):
		self._forwarder2id[forwarder] = id
		self._id2forwarder[id] = forwarder
	def remove(self, forwarder_or_id):
		if isinstance(forwarder_or_id, Forwarder):
			forwarder = forwarder_or_id
			id = self._forwarder2id[forwarder]
		elif isinstance(forwarder_or_id, int):
			id = forwarder_or_id
			forwarder = self._id2forwarder[id]
		else:
			raise Exception('BiMap.remove fuck')
		self._forwarder2id.pop(forwarder)
		self._id2forwarder.pop(id)
	def forwarder2id(self, forwarder):
		assert isinstance(forwarder, Forwarder)
		return self._forwarder2id.get(forwarder)
	def id2forwarder(self, id):
		assert isinstance(id, int)
		return self._id2forwarder.get(id)
	def has_forwarder(self, forwarder):
		return forwarder in self._forwarder2id
	def has_id(self, id):
		return id in self._id2forwarder
	def all_ids(self):
		return self._id2forwarder.keys()

class WPForwarderManager():
	def __init__(self, link):
		self.link = link
		self.bimap = BiMap()
		self._next_id = 1

	def close_all_fowarders(self):
		for id in self.bimap.all_ids():
			self.close_forwarder(id)

	def close_forwarder(self, forwarder_or_id):
		if isinstance(forwarder_or_id, Forwarder):
			forwarder = forwarder_or_id
			id = self.bimap.forwarder2id(forwarder)
			assert id
			self.link.close_connection(id)
		elif isinstance(forwarder_or_id, int):
			id = forwarder_or_id
			forwarder = self.bimap.id2forwarder(id)
			if not forwarder:
				self.link.closeLinkWithMsg('invalid connetion id : %d'%connection_id)
				return
			forwarder.master.forwarder_closed('closed by another side of link')
		else:
			assert False
		self.bimap.remove(forwarder_or_id)

	def send_data_to_forwarder(self, id, data):
		forwarder = self.bimap.id2forwarder(id)
		if not forwarder:
			self.link.closeLinkWithMsg('invalid connection id'%connection_id)
			return
		forwarder.forward_data_to_master(data)
		print 'manager : forward data to master'

	def send_data_to_link(self, forwarder, data):
		id = self.bimap.forwarder2id(forwarder)
		assert id
		self.link.send_data(id, data)

class WPClientForwarderManager(WPForwarderManager):
	def create_forwarder(self, master, addr):
		forwarder = WPForwarder(master, self)
		id = self._next_id
		self._next_id += 1
		self.bimap.add(forwarder, id)
		self.link.create_connection(id, addr[0], addr[1])
		return forwarder

class WPServerForwarderManager(WPForwarderManager):
	def create_forwarder(self, id, addr):
		if self.bimap.has_id(id):
			self.link.closeLinkWithMsg('connection id %d already used'%id)
			return
		f1,_ = create_connected_forwarders(WPForwarder, [self], create_direct_forwarder, [addr])
		self.bimap.add(f1, id)
		return f1

class ForwarderMaster():
	def __init__(self):
		self.forwarder = None
		self._forwarder_closed = False
		self._forwarder_closed_reason = None
		self._forwarder_creation_failed = False
		self._forwarder_creation_failed_reason = None
	def forward_data_received(self, data):
		raise NotImplementedError()
	def forwarder_closed(self, reason):
		assert self.forwarder and not self._forwarder_closed
		self.forwarder = None
		self._forwarder_closed = False
		self._forwarder_closed_reason = reason
	def forwarder_created(self, forwarder):
		assert not self.forwarder and not self._forwarder_closed
		self.forwarder = forwarder
	def forwarder_create_failed(self, reason):
		assert not self.forwarder and not self._forwarder_closed
		self._forwarder_creation_failed = True
		self._forwarder_creation_failed_reason = reason

class Forwarder():
	def __init__(self, master):
		self.master = master

	def forward_data_to_master(self, data):
		self.master.forward_data_received(data)

	def forward_data_from_master(self, data):
		raise NotImplementedError()

	def master_closed(self, reason):
		self.master = None
		log.msg('master closed for : %s' % str(reason))

class WPForwarder(Forwarder):
	def __init__(self, master, manager):
		Forwarder.__init__(self, master)
		self.manager = manager
		from twisted.internet import reactor
		reactor.callLater(0, self.master.forwarder_created, self)

	def data_received_from_link(self, data):
		self.forward_data_to_master(data)

	def forward_data_from_master(self, data):
		self.manager.send_data_to_link(self, data)

	def master_closed(self, reason):
		self.manager.close_forwarder(self)
		Forwarder.master_closed(self, reason)

class DirectForwardProtocol(Protocol, Forwarder):
	def connectionMade(self):
		self.master.forwarder_created(self)
	def connectionLost(self, reason):
		self.master.forwarder_closed(reason)
	def dataReceived(self, data):
		self.master.forward_data_received(data)
	def forward_data_from_master(self, data):
		log.msg('DirectForwardProtocol.forward_data_from_master')
		self.transport.write(data)
	def master_closed(self, reason):
		self.loseConnection(reason)

class DirectForwardFactory(ClientFactory):
	def __init__(self, master):
		self.master = master

	def buildProtocol(self, addr):
		p = DirectForwardProtocol(self.master)
		p.factory = self
		return p

	def clientConnectionFailed(self, connector, reason):
		self.master.forwarder_create_failed(reason)

class OneSideMaster(ForwarderMaster):
	def __init__(self):
		self.another_side = None
		self._pending_data_arr = []
		ForwarderMaster.__init__(self)
	def set_another_side(self, another_side):
		self.another_side = another_side
	def set_forwarder(self, forwarder):
		self.forwarder = forwarder
	def another_forwader_created(self):
		assert self.another_side.forwarder
		assert self.another_side.forwarder != self.forwarder
		for pending_data in self._pending_data_arr:
			self.another_side.forwarder.forward_data_from_master(pending_data)
		if self._forwarder_closed:
			self.another_side.forwarder.master_closed(self._forwarder_closed_reason)
	def forward_data_received(self, data):
		if not self.another_side.forwarder:
			self._pending_data_arr.append(data)
		else:
			self.another_side.forwarder.forward_data_from_master(data)

	def forwarder_closed(self, reason):
		ForwarderMaster.forwarder_closed(self, reason)
		if self.another_side.forwarder:
			self.another_side.forwarder.master_closed(reason)

	def forwarder_created(self, forwarder):
		ForwarderMaster.forwarder_created(self, forwarder)
		self.another_side.another_forwader_created()

	def forwarder_create_failed(self, reason):
		ForwarderMaster.forwarder_create_failed(self, reason)
		if self.another_side.forwarder:
			self.another_side.forwarder.master_closed(reason)

def create_connected_forwarders(creator_1, args_1, creator_2, args_2):
	m1 = OneSideMaster()
	m2 = OneSideMaster()
	m1.set_another_side(m2)
	m2.set_another_side(m1)
	f1 = creator_1(m1, *args_1)
	f2 = creator_2(m2, *args_2)
	return (f1, f2)

def create_wp_forwarder(master, manager, addr):
	return manager.create_forwarder(master, addr)

def create_direct_forwarder(master, addr):
	f = DirectForwardFactory(master)
	from twisted.internet import reactor
	reactor.connectTCP(addr[0], addr[1], f)
	return None