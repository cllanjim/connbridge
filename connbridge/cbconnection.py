from twisted.python import log
from proxy import ProxyClient, proxy_connect

class CBConnectionClient:
	def __init__(self):
		self.cb_connection = None
	def cb_connected(self):
		pass
	def cb_data_received(self, data):
		pass
	def cb_connect_failed(self):
		pass
	def cb_connection_lost(self):
		pass

class CBConnection():
	def __init__(self, bridge, id):
		self.bridge = bridge
		self.id = id
		self.remote_closed = False
		self.closed = False

	def send(self, data):
		self.bridge.cb_send(self.id, data)

	def on_remote_closed(self):
		raise NotImplementedError()

	def on_remote_data_received(self, data):
		raise NotImplementedError()

class CBClientConnection(CBConnection):
	def __init__(self, bridge, id, client):
		CBConnection.__init__(self, bridge, id)
		self.client = client

	def close(self):
		if not self.closed:
			self.closed = True
			self.bridge.cb_close(self.id)

	def on_remote_closed(self):
		log.msg('on_remote_closed : %d'%self.id)
		if not self.closed:
			self.closed = True
			self.client.cb_connection_lost()

	def on_remote_data_received(self, data):
		self.client.cb_data_received(data)

	def connect_failed(self):
		log.msg('connect_failed')
		self.closed = True
		self.client.cb_connect_failed()

	def connected(self):
		log.msg('connected')
		self.client.cb_connected()

class CBServerConnection(CBConnection, ProxyClient):
	def __init__(self, bridge, id, host, port, cb_connect_cmd_id):
		CBConnection.__init__(self, bridge, id)
		ProxyClient.__init__(self)
		self.cb_connect_cmd_id = cb_connect_cmd_id
		proxy_connect(host, port, self)

	def _close(self):
		if not self.closed:
			self.closed = True
			self.bridge.cb_close(self.id)

	def on_remote_closed(self):
		if not self.closed:
			self.closed = True
			self.proxy.close()

	def on_remote_data_received(self, data):
		self.proxy.send(data)

	# proxy client callbacks
	def proxy_connected(self):
		ProxyClient.proxy_connected(self)
		self.bridge.responde_cb_connect(self.cb_connect_cmd_id)
	def proxy_data_received(self, data):
		self.send(data)
	def proxy_connection_lost(self, reason):
		self._close()
	def proxy_connect_failed(self, reason):
		self.bridge.responde_error(self.cb_connect_cmd_id, reason)
		self._close()
