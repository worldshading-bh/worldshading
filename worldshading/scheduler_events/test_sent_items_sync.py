from __future__ import unicode_literals

import unittest
from types import SimpleNamespace

try:
	from unittest.mock import MagicMock, patch
except ImportError:
	from mock import MagicMock, patch

from worldshading.scheduler_events import sent_items_sync


class TestSentItemsSyncScheduling(unittest.TestCase):
	@patch.object(sent_items_sync, "_release_account_lock")
	@patch.object(sent_items_sync, "_acquire_account_lock")
	@patch.object(sent_items_sync, "enqueue")
	@patch.object(sent_items_sync, "get_jobs")
	@patch.object(sent_items_sync.frappe, "get_all")
	def test_scheduler_enqueues_each_available_account_once(
		self, get_all, get_jobs, enqueue, acquire_lock, release_lock
	):
		get_all.return_value = [
			SimpleNamespace(name="accounts@example.com"),
			SimpleNamespace(name="sales@example.com"),
		]
		get_jobs.return_value = {
			"test-site": ["sent_items_sync|accounts@example.com"]
		}
		acquire_lock.return_value = True

		with patch.object(
			sent_items_sync.frappe,
			"local",
			SimpleNamespace(site="test-site"),
		):
			sent_items_sync.sync_sent_items()

		enqueue.assert_called_once_with(
			sent_items_sync.sync_sent_items_for_account,
			"short",
			timeout=sent_items_sync.ACCOUNT_JOB_TIMEOUT_SECONDS,
			event="all",
			job_name="sent_items_sync|sales@example.com",
			account_name="sales@example.com",
		)
		acquire_lock.assert_called_once_with("sales@example.com")
		release_lock.assert_not_called()

	@patch.object(sent_items_sync, "_release_account_lock")
	@patch.object(sent_items_sync, "_sync_account")
	def test_account_job_always_releases_scheduler_lock(
		self, sync_account, release_lock
	):
		sync_account.side_effect = RuntimeError("mail server unavailable")

		with self.assertRaises(RuntimeError):
			sent_items_sync.sync_sent_items_for_account("accounts@example.com")

		release_lock.assert_called_once_with("accounts@example.com")


class TestTimedImapConnection(unittest.TestCase):
	def test_ssl_connection_uses_explicit_socket_timeout(self):
		self.assertTrue(hasattr(sent_items_sync, "_TimedIMAP4SSL"))
		self.assertTrue(hasattr(sent_items_sync, "socket"))

		with patch.object(
			sent_items_sync.socket, "create_connection"
		) as create_connection:
			raw_socket = MagicMock()
			wrapped_socket = MagicMock()
			create_connection.return_value = raw_socket
			client = object.__new__(sent_items_sync._TimedIMAP4SSL)
			client.host = "mail.example.com"
			client.port = 993
			client.connection_timeout = 15
			client.ssl_context = MagicMock()
			client.ssl_context.wrap_socket.return_value = wrapped_socket

			result = client._create_socket()

			create_connection.assert_called_once_with(
				("mail.example.com", 993), 15
			)
			client.ssl_context.wrap_socket.assert_called_once_with(
				raw_socket, server_hostname="mail.example.com"
			)
			self.assertIs(result, wrapped_socket)


if __name__ == "__main__":
	unittest.main()
