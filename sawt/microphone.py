"""Bridge caller-only microphone state to native GPT-Live input controls.

No output mute, response interruption, transaction mutation or mic audio logging.
Browser capture also supplies silence so a lost command never leaks muted speech.
"""
from __future__ import annotations
import json


class MicrophoneBridge:
    def __init__(self, sid, room, session, audit):
        self.sid, self.room, self.session, self.audit = sid, room, session, audit
        self.sequence = -1
        self.muted = False
        self.pending = {}
        self.bound = False

    def bind(self):
        self.room.on('data_received', self.on_packet)
        self.session.on('openai_client_event_queued', self.on_client_event)
        self.session.on('openai_server_event_received', self.on_server_event)
        self.bound = True

    def close(self):
        if not self.bound:
            return
        self.bound = False
        self.room.off('data_received', self.on_packet)
        self.session.off('openai_client_event_queued', self.on_client_event)
        self.session.off('openai_server_event_received', self.on_server_event)
        self.pending.clear()

    def on_packet(self, packet):
        if (getattr(packet, 'topic', None) != 'sawt-mic'
                or getattr(getattr(packet, 'participant', None), 'identity', None) != 'caller-' + self.sid):
            return
        try:
            if len(packet.data) > 512:
                return
            data = json.loads(packet.data)
            if (not isinstance(data, dict) or set(data) != {'call_id', 'muted', 'sequence'}
                    or data['call_id'] != self.sid or type(data['muted']) is not bool
                    or type(data['sequence']) is not int or not 0 <= data['sequence'] <= 1000000
                    or data['sequence'] <= self.sequence):
                return
            method = getattr(self.session, 'mute_input' if data['muted'] else 'unmute_input', None)
            if not callable(method):
                self.audit('voice.input_mute_unavailable', {})
                return
            self.sequence, self.muted = data['sequence'], data['muted']
            method()
            self.audit('voice.input_mute_requested', {'muted': self.muted, 'sequence': self.sequence})
        except (ValueError, TypeError, UnicodeError):
            return
        except Exception as exc:
            self.audit('voice.input_mute_failed', {'error_type': type(exc).__name__})

    def on_client_event(self, event):
        kind = event.get('type')
        if kind not in ('session.input_audio.mute', 'session.input_audio.unmute'):
            return
        key = event.get('event_id')
        if isinstance(key, str):
            if len(self.pending) >= 32:
                self.pending.pop(next(iter(self.pending)))
            self.pending[key] = {'muted': kind.endswith('.mute'), 'sequence': self.sequence}

    def on_server_event(self, event):
        kind = event.get('type')
        if kind not in ('session.input_audio.muted', 'session.input_audio.unmuted'):
            return
        pending = self.pending.pop(event.get('client_event_id'), None)
        if pending is not None:
            applied = kind.endswith('.muted')
            if applied == pending['muted']:
                self.audit('voice.input_mute_applied', pending)
