# Copyright (C) 2004 Anthony Baxter
"""Tests for shtoom.avail.
"""

from twisted.trial import unittest

class AvailTest(unittest.TestCase):

    def test_audioAvail(self):
        from shtoom.avail.audio import listAudio
        self.assertTrue(len(listAudio()) > 0)

    def test_codecAvail(self):
        from shtoom.avail.codecs import listCodecs
        self.assertTrue(len(listCodecs()) > 0, listCodecs())
