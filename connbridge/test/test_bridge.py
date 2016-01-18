from twisted.trial import unittest
from twisted.test.proto_helpers import StringTransport
from twisted.internet.protocol import Protocol
from connbridge.bridge import DefaultBridgeClient, DefaultBridgeServer, LoginException

class _DummyPassUserManager:
	def login(self, username, password):
		return True

class _DummyFailUserManager:
	def login(self, username, password):
		return False

class _TestCaseMixin:
	def _feed_server(self):
		data = self.client_tr.value()
		self.client_tr.clear()
		self.assertTrue(data)
		self.server.dataReceived(data)

	def _feed_client(self):
		data = self.server_tr.value()
		self.server_tr.clear()
		self.assertTrue(data)
		self.client.dataReceived(data)

	def _assertClientRaise(self, e):
		with self.assertRaises(e):
			self._feed_client()

	def _assertServerRaise(self, e):
		with self.assertRaises(e):
			self._feed_server()

class BridgeLoginTest(_TestCaseMixin, unittest.TestCase):
	def setUp(self):
		self.client = DefaultBridgeClient()
		self.client.raise_exception = True
		self.client_tr = StringTransport()
		self.client.makeConnection(self.client_tr)
		self.server = DefaultBridgeServer(None)
		self.server.raise_exception = True
		self.server_tr = StringTransport()
		self.server.makeConnection(self.server_tr)

	def test_login_pass(self):
		self.server.user_manager = _DummyPassUserManager()
		d = self.client.login('0.1', 'abc', '123456')
		self._feed_server()
		self._feed_client()
		self.assertTrue(self.client._logined)
		return d

	def test_login_fail(self):
		self.server.user_manager = _DummyFailUserManager()
		d = self.client.login('0.1', 'abc', '123456')
		self._assertServerRaise(LoginException)
		self._feed_client()
		self.assertFalse(self.client._logined)
		return d
