# Copyright (C) 2004 Anthony Baxter
from shtoom.rtp.formats import PT_PCMU, PT_GSM, PT_SPEEX, PT_DVI4, PT_RAW
from shtoom.rtp.formats import PT_PCMA, PT_ILBC
from shtoom.rtp.formats import PT_CN, PT_xCN, AudioPTMarker
from shtoom.avail import codecs
from shtoom.audio import aufile, playout
from shtoom.lwc import Interface, implements

from twisted.python import log

#import sets
import struct

try:
    import audioop
except ImportError:
    audioop = None

class NullEncoder:
    def handle_audio(self, data):
        pass

nullencoder = NullEncoder()

class MediaSample:
    def __init__(self, ct, data):
        self.ct = ct
        self.data = data

    def __repr__(self):
        return "<%s/%s, %s>" % (self.__class__.__name__, self.ct, self.data,)

class NullConv:
    # XXX Should be refactored away - MediaLayer is the only derived class
    def __init__(self, device):
        self._d = device
    def getDevice(self):
        return self._d
    def setDevice(self, d):
        self._d = d
    def getFormats(self):
        if self._d:
            return self._d.getFormats()
    def write(self, data):
        if self._d:
            return self._d.write(data)
    def close(self):
        if self._d:
            log.msg("audio device %r close"%(self._d,), system="audio")
            return self._d.close()
    def reopen(self):
        if self._d:
            log.msg("audio device %r reopen ..."%(self._d,), system="audio")
            return self._d.reopen()
    def isOpen(self):
        if self._d:
            return self._d.isOpen()
    def __repr__(self):
        return '<%s wrapped around %r>'%(self.__class__.__name__, self._d)

def isLittleEndian():
    # deprecated way to check endianness
    #import struct
    #p = struct.pack('H', 1)
    #if p == '\x01\x00':
    #    return True
    #elif p == '\x00\x01':
    #    return False
    #else:
    #    raise ValueError("insane endian-check result %r"%(p))
    # better way for Python 3.3 and up:
    import sys
    if sys.byteorder == 'little': 
        return True
    return False

class IAudioCodec:
    def buffer_and_encode(self, payload):
        "encode payload, some bytes of audio"
    def decode(self, payload):
        "decode payload, some bytes of audio"

class _Codec:
    """Base class for codecs"""
    implements(IAudioCodec)
    def __init__(self, samplesize):
        self.samplesize = samplesize
        self.b = b''

    def buffer_and_encode(self, payload):
        self.b += payload
        res = []
        while len(self.b) >= self.samplesize:
            sample, self.b = self.b[:self.samplesize], self.b[self.samplesize:]
            res.append(self._encode(sample))
        return res

class GSMCodec(_Codec):
    def __init__(self):
        _Codec.__init__(self, 320)
        if isLittleEndian():
            self.enc = codecs.gsm.gsm(codecs.gsm.LITTLE)
            self.dec = codecs.gsm.gsm(codecs.gsm.LITTLE)
        else:
            self.enc = codecs.gsm.gsm(codecs.gsm.BIG)
            self.dec = codecs.gsm.gsm(codecs.gsm.BIG)

    def _encode(self, payload):
        assert isinstance(payload, bytes), "payload is not an instance of bytes"
        return self.enc.encode(payload)

    def decode(self, payload):
        assert isinstance(payload, bytes), "payload is not an instance of bytes"
        if len(payload) != 33:
            log.msg("GSM: short read on decode, %d !=  33"%len(payload),
                                                            system="codec")
            return None
        return self.dec.decode(payload)

class SpeexCodec(_Codec):
    "A codec for Speex"

    def __init__(self):
        self.enc = codecs.speex.new(8)
        self.dec = codecs.speex.new(8)
        _Codec.__init__(self, 320)

    def _encode(self, payload, unpack=struct.unpack):
        assert isinstance(payload, bytes), "payload is not an instance of bytes"
        frames = list(unpack('160h', payload))
        return self.enc.encode(frames)

    def decode(self, payload):
        assert isinstance(payload, bytes), "payload is not an instance of bytes"
        if len(payload) != 40:
            log.msg("speex: short read on decode %d != 40"%len(payload),
                                                            system="codec")
            return None
        frames = self.dec.decode(payload)
        ostr = struct.pack('160h', *frames)
        return ostr

class MulawCodec(_Codec):
    """A codec for mulaw encoded audio (G.711U, PCMU)"""

    def __init__(self):
        _Codec.__init__(self, 320)
        self.buf = b''

    def _encode(self, payload):
        assert isinstance(payload, bytes), "payload is not an instance of bytes"
        return audioop.lin2ulaw(payload, 2)

    def decode(self, payload):
        assert isinstance(payload, bytes), "payload is not an instance of bytes"
        if not payload:
            return
        elif len(payload) != 160:
            log.msg("mulaw: short read on decode, %d != 160"%len(payload),
                                                            system="codec")
            # Pad with silence.
            extra = (160 - len(payload)) * payload[-1]
            payload += extra
        if 0:
            payload = audioop.ulaw2lin(payload, 2)
            self.buf += payload
            if len(self.buf) > 159:
                out, self.buf = self.buf[:160], self.buf[160:]
                return out
        else:
            return audioop.ulaw2lin(payload, 2)

class AlawCodec(_Codec):
    "A codec for alaw encoded audio (G.711A, PCMA)"

    def __init__(self):
        _Codec.__init__(self, 320)

    def _encode(self, payload):
        assert isinstance(payload, bytes), "payload is not an instance of bytes"
        return audioop.lin2alaw(payload, 2)

    def decode(self, payload):
        assert isinstance(payload, bytes), "payload is not an instance of bytes"
        if len(payload) != 160:
            log.msg("alaw: short read on decode, %d != 160"%len(payload),
                                                            system="codec")
        return audioop.alaw2lin(payload, 2)

class NullCodec(_Codec):
    """A codec that consumes/emits nothing (e.g. for comfort noise)"""

    def __init__(self):
        _Codec.__init__(self, 1)

    def _encode(self, payload):
        assert isinstance(payload, bytes), "payload is not an instance of bytes"
        return None

    def decode(self, payload):
        assert isinstance(payload, bytes), "payload is not an instance of bytes"
        return None

class PassthruCodec(_Codec):
    """A codec that leaves it's input alone"""
    def __init__(self):
        _Codec.__init__(self, None)
    decode = lambda self, payload: payload
    buffer_and_encode = lambda self, payload: [payload]

def make_codec_set():
    format_to_codec = {}
    format_to_codec[PT_CN] = NullCodec()
    format_to_codec[PT_xCN] = NullCodec()
    format_to_codec[PT_RAW] = PassthruCodec()
    assert codecs.mulaw
    if codecs.mulaw is not None:
        format_to_codec[PT_PCMU] = MulawCodec()
    if codecs.alaw is not None:
        format_to_codec[PT_PCMA] = AlawCodec()
    if codecs.gsm is not None:
        format_to_codec[PT_GSM] = GSMCodec()
    if codecs.speex is not None:
        format_to_codec[PT_SPEEX] = SpeexCodec()
    #if codecs.dvi4 is not None:
    #    format_to_codec[PT_DVI4] = DVI4Codec()
    #if codecs.ilbc is not None:
    #    format_to_codec[PT_ILBC] = ILBCCodec()
    return format_to_codec

# changed for Python 3
# sets.ImmutableSet ==> frozenset
known_formats = (frozenset(make_codec_set().keys()) -
                                  frozenset([PT_CN, PT_xCN,]))

class Codecker:
    def __init__(self, format):
        self.format_to_codec = make_codec_set()
        if not format in known_formats:
            raise ValueError("Can't handle codec %r"%format)
        self.format = format
        self.handler = None

    def set_handler(self, handler):
        """
        handler will subsequently receive calls to handle_media_sample().
        """
        self.handler = handler

    def getDefaultFormat(self):
        return self.format

    def handle_audio(self, payload):
        """Accept audio as bytes, emits MediaSamples."""
        assert isinstance(payload, bytes), "payload is not an instance of bytes"
        if not payload:
            return None
        codec = self.format_to_codec.get(self.format)
        if not codec:
            raise ValueError("can't encode format %r"%self.format)
        encaudios = codec.buffer_and_encode(payload)
        for encaudio in encaudios:
            samp = MediaSample(self.format, encaudio)
            if self.handler is not None:
                self.handler(samp)
            else:
                return samp

    def decode(self, packet):
        """Accepts an RTPPacket, emits audio as bytes"""
        if not packet.data:
            return None
        codec = self.format_to_codec.get(packet.header.ct)
        if not codec:
            raise ValueError("can't decode format %r"%packet.header.ct)
        encaudio = codec.decode(packet.data)
        return encaudio

class MediaLayer(NullConv):
    """ The MediaLayer sits between the network and the raw
        audio device. It converts the audio to/from the codec on
        the network to the format used by the lower-level audio
        devices (16 bit signed ints at an integer multiple of 8KHz).
    """

    _playfile_LC = None
    _playfile_fp = None

    def __init__(self, device, *args, **kwargs):
        self.playout = None
        self.codecker = None
        self.defaultFormat = None
        # this sets self._d = device
        NullConv.__init__(self, device, *args, **kwargs)

    def getFormat(self):
        return self.defaultFormat

    def write(self, packet):
        if self.playout is None:
            log.msg("write before reopen, discarding")
            return 0
        audio = self.codecker.decode(packet)
        if audio:
            return self.playout.write(audio, packet.header.seq)
        else:
            self.playout.write('', packet.header.seq)
            return 0

    def selectDefaultFormat(self, fmts=[PT_PCMU,]):
        assert isinstance(fmts, (list, tuple,)), fmts
        assert not self._d or not self._d.isOpen(), \
            "close device %r before calling selectDefaultFormat()" % (self._d,)

        for f in fmts:
            if f in known_formats:
                self.defaultFormat = f
                break
        else:
            raise ValueError("No working formats!")

    def reopen(self, mediahandler=None):
        """
        mediahandler, if not None, is a callable that will be called with
        a media sample is available.

        This flushes codec buffers.  The audio playout buffers and microphone
        readin buffers *ought* to be flushed by the lower-layer audio device
        when we call reopen() on it.
        """
        assert self.defaultFormat, "must call selectDefaultFormat()"+\
                                   "before (re-)opening the device."

        self.codecker = Codecker(self.defaultFormat)
        self._d.reopen()
        if mediahandler:
            self.codecker.set_handler(mediahandler)
            self._d.set_encoder(self.codecker)
        else:
            self._d.set_encoder(nullencoder)

        if self.playout:
            log.msg("playout already started")
        else:
            self.playout = playout.Playout(self)

    def playWaveFile(self, fname):
        from twisted.internet.task import LoopingCall
        # stop any existing wave file playback
        self.stopWaveFile()
        if not self._d.isOpen():
            self.selectDefaultFormat([PT_PCMU,])
            self.reopen()
        else:
            self.close()
            self.selectDefaultFormat([PT_PCMU,])
            self.reopen()
        self._playfile_fp = aufile.WavReader(fname)
        self._playfile_LC = LoopingCall(self._playWaveFileLoopingCall)
        self._playfile_LC.start(0.020)

    def _playWaveFileLoopingCall(self):
        if self._playfile_fp is None:
            return
        data = self._playfile_fp.read(160)
        if data:
            self._d.write(data)
        else:
            self._playfile_fp.reset()

    def stopWaveFile(self):
        if self._playfile_LC is not None:
            self._playfile_LC.stop()
            self._playfile_LC = None
            self._playfile_fp = None

    def close(self):
        self.playout = None
        self.codecker = None
        self._d.set_encoder(nullencoder)
        NullConv.close(self)

class DougConverter(MediaLayer):
    "Specialised converter for Doug."
    # XXX should be refactored away to just use a Codecker directly
    def __init__(self, defaultFormat=PT_PCMU, *args, **kwargs):
        self.codecker = Codecker(defaultFormat)
        self.convertInbound = self.codecker.decode
        self.convertOutbound = self.codecker.handle_audio
        self.set_handler = self.codecker.set_handler
        if not kwargs.get('device'):
            kwargs['device'] = None
        NullConv.__init__(self, *args, **kwargs)
