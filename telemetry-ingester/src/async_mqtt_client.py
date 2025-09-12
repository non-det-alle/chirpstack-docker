"""
Coroutine version of the loop_forever() primitive from paho.mqtt.client.Client
via asyncio reimplementation of the select function for waiting on sockets
"""

import asyncio

from paho.mqtt.enums import MQTTErrorCode, _ConnectionState
from paho.mqtt.client import Client, MQTT_LOG_DEBUG


async def select_async(rlist, wlist, timeout=None) -> tuple[list, list]:
    # inspired by asyncio.wait source code
    rlist, wlist = set(rlist), set(wlist)
    
    loop = asyncio.get_running_loop()
    waiter = loop.create_future()

    def _release_waiter():
        if not waiter.done():
            waiter.set_result(None)

    timeout_handle = None
    if timeout is not None:
        timeout_handle = loop.call_later(timeout, _release_waiter)

    rout, wout = set(), set()

    def _on_completion(callback, *args):
        if timeout_handle is not None:
            timeout_handle.cancel()
        if not waiter.done():
            waiter.set_result(None)
        callback(*args)

    for fd in rlist:
        loop.add_reader(fd, _on_completion, rout.add, fd)
    for fd in wlist:
        loop.add_writer(fd, _on_completion, wout.add, fd)
    
    try:
        await waiter
    finally:
        if timeout_handle is not None:
            timeout_handle.cancel()
        for fd in rlist:
            loop.remove_reader(fd)
        for fd in wlist:
            loop.remove_writer(fd)
            
    return list(rout), list(wout)


class ClientAsync(Client):
    async def _loop_async(self, timeout: float = 1.0) -> MQTTErrorCode:
        if timeout < 0.0:
            raise ValueError('Invalid timeout.')

        if self.want_write():
            wlist = [self._sock]
        else:
            wlist = []

        # used to check if there are any bytes left in the (SSL) socket
        pending_bytes = 0
        if hasattr(self._sock, 'pending'):
            pending_bytes = self._sock.pending()  # type: ignore[union-attr]

        # if bytes are pending do not wait in select
        if pending_bytes > 0:
            timeout = 0.0

        # sockpairR is used to break out of select() before the timeout, on a
        # call to publish() etc.
        if self._sockpairR is None:
            rlist = [self._sock]
        else:
            rlist = [self._sock, self._sockpairR]

        try:
            socklist = await select_async(rlist, wlist, timeout)
        except TypeError:
            # Socket isn't correct type, in likelihood connection is lost
            # ... or we called disconnect(). In that case the socket will
            # be closed but some loop (like loop_forever) will continue to
            # call _loop(). We still want to break that loop by returning an
            # rc != MQTT_ERR_SUCCESS and we don't want state to change from
            # mqtt_cs_disconnecting.
            if self._state not in (_ConnectionState.MQTT_CS_DISCONNECTING, _ConnectionState.MQTT_CS_DISCONNECTED):
                self._state = _ConnectionState.MQTT_CS_CONNECTION_LOST
            return MQTTErrorCode.MQTT_ERR_CONN_LOST
        except ValueError:
            # Can occur if we just reconnected but rlist/wlist contain a -1 for
            # some reason.
            if self._state not in (_ConnectionState.MQTT_CS_DISCONNECTING, _ConnectionState.MQTT_CS_DISCONNECTED):
                self._state = _ConnectionState.MQTT_CS_CONNECTION_LOST
            return MQTTErrorCode.MQTT_ERR_CONN_LOST
        except Exception:
            # Note that KeyboardInterrupt, etc. can still terminate since they
            # are not derived from Exception
            return MQTTErrorCode.MQTT_ERR_UNKNOWN

        if self._sock in socklist[0] or pending_bytes > 0:
            rc = self.loop_read()
            if rc or self._sock is None:
                return rc

        if self._sockpairR and self._sockpairR in socklist[0]:
            # Stimulate output write even though we didn't ask for it, because
            # at that point the publish or other command wasn't present.
            socklist[1].insert(0, self._sock)
            # Clear sockpairR - only ever a single byte written.
            try:
                # Read many bytes at once - this allows up to 10000 calls to
                # publish() inbetween calls to loop().
                self._sockpairR.recv(10000)
            except BlockingIOError:
                pass

        if self._sock in socklist[1]:
            rc = self.loop_write()
            if rc or self._sock is None:
                return rc

        return self.loop_misc()
    
    async def loop_forever_async(
        self,
        timeout: float = 1.0,
        retry_first_connection: bool = False,
    ) -> MQTTErrorCode:
        """This function calls the network loop functions for you in an
        infinite blocking loop. It is useful for the case where you only want
        to run the MQTT client loop in your program.

        loop_forever() will handle reconnecting for you if reconnect_on_failure is
        true (this is the default behavior). If you call `disconnect()` in a callback
        it will return.

        :param int timeout: The time in seconds to wait for incoming/outgoing network
          traffic before timing out and returning.
        :param bool retry_first_connection: Should the first connection attempt be retried on failure.
          This is independent of the reconnect_on_failure setting.

        :raises OSError: if the first connection fail unless retry_first_connection=True
        """

        run = True

        while run:
            if self._thread_terminate is True:
                break

            if self._state == _ConnectionState.MQTT_CS_CONNECT_ASYNC:
                try:
                    self.reconnect()
                except OSError:
                    self._handle_on_connect_fail()
                    if not retry_first_connection:
                        raise
                    self._easy_log(
                        MQTT_LOG_DEBUG, "Connection failed, retrying")
                    self._reconnect_wait()
            else:
                break

        while run:
            rc = MQTTErrorCode.MQTT_ERR_SUCCESS
            while rc == MQTTErrorCode.MQTT_ERR_SUCCESS:
                rc = await self._loop_async(timeout)
                # We don't need to worry about locking here, because we've
                # either called loop_forever() when in single threaded mode, or
                # in multi threaded mode when loop_stop() has been called and
                # so no other threads can access _out_packet or _messages.
                if (self._thread_terminate is True
                    and len(self._out_packet) == 0
                        and len(self._out_messages) == 0):
                    rc = MQTTErrorCode.MQTT_ERR_NOMEM
                    run = False

            def should_exit() -> bool:
                return (
                    self._state in (_ConnectionState.MQTT_CS_DISCONNECTING, _ConnectionState.MQTT_CS_DISCONNECTED) or
                    run is False or  # noqa: B023 (uses the run variable from the outer scope on purpose)
                    self._thread_terminate is True
                )

            if should_exit() or not self._reconnect_on_failure:
                run = False
            else:
                self._reconnect_wait()

                if should_exit():
                    run = False
                else:
                    try:
                        self.reconnect()
                    except OSError:
                        self._handle_on_connect_fail()
                        self._easy_log(
                            MQTT_LOG_DEBUG, "Connection failed, retrying")

        return rc # type: ignore