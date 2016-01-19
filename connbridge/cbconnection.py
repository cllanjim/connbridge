from proxy import ProxyClient

class CBConnectionClient:
	def cb_connected(self):
		pass
	def cb_connect_failed(self):
		pass
	def cb_data_received(self, data):
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

	def close(self):
		if not self.closed:
			self.closed = True
			self.bridge.cb_close(self.id)
			self.bridge = None
			self.id = None

	#called from bridge
	def on_remote_closed(self):
		assert not self._closed
		self.remote_closed = True
		self.close()
	def on_remote_data_received(self, data):
		pass

class CBClientConnection(CBConnection):
	def __init__(self, bridge, id, client):
		CBConnection.__init__(self, bridge, id)
		self.client = client

	def close(self):
		CBConnection.close(self)
		if not self.closed:
			self.client.cb_connection_lost()
			self.client = None

	def on_remote_data_received(self, data):
		self.client.cb_data_received(data)

class CBServerConnection(CBConnection, ProxyClient):
	def __init__(self, bridge, id, host, port, cb_connect_cmd_id):
		CBConnection.__init__(self, bridge, id)
		ProxyClient.__init__(self)
		self.proxy_conncet(host, port)
		self.cb_connect_cmd_id = cb_connect_cmd_id

	def close(self):
		CBConnection.close(self)
		if not self.closed:
			self.proxy_close()

	def on_remote_data_received(self, data):
		self.proxy_send_data(data)

	# proxy client callbacks
	def proxy_connected(self):
		ProxyClient.proxy_connected(self)
		self.bridge.responde_cb_connect(self.cb_connect_cmd_id)
	def proxy_data_received(self, data):
		self.send(data)
	def proxy_connection_lost(self, reason):
		self.close()
	def proxy_connect_failed(self, reason):
		self.close()
