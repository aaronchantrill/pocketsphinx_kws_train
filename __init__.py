# -*- coding: utf-8 -*-
import os
import sqlite3
from naomi import paths
from naomi import plugin
from naomi import profile


# The stt_trainer plugin provides a plugin that is used with the
# NaomiSTTTrainer.py program to train a stt engine based on the
# contents of your audiolog database.
#
# The audiolog database is a database of recordings of you speaking
# to your Naomi. Actual recordings of you speaking to your Naomi
# are the best source of training material since the resulting STT
# model will be adapted to your voice, background noise, microphone,
# etc.
#
# To start saving recordings, run Naomi with the --save-audio flag.
# This will save any audio picked up any time the Voice Activity
# Detector indicates that Naomi should start listening. This will
# include passive phrases ("Naomi"), active phrases ("what time is
# it"), people speaking near Naomi but not to Naomi, and, depending
# on your VAD plugin, even loud noises.
#
# After collecting about 50 recordings or so, you probably want to
# switch to only collecting active phrases, which means that audio
# will only be collected once Naomi thinks it has heard its wake word.
#
# This can be accomplished by adding the following to your profile.yml:
#   audiolog:
#     save_active_audio: True
#
# The NaomiSTTTrainer.py program allows you to review recordings,
# verify or correct transcriptions, associate recordings with
# specific speakers, and verify or correct intents associated with
# the recordings.
#
# Once you have a database of recordings built up, you can then use
# that information to train a specific STT engine. That is where this
# plugin comes in.
class Pocketsphinx_KWS_Train(plugin.STTTrainerPlugin):
    # The only required method for this this plugin type is HandleCommand.
    # This method receives a command and description and returns an HTML
    # response, the next command and a description. The reason for this
    # is because it can take a very long time to actually train a STT
    # engine, and that training can typically be split into distinct
    # stages or loops, with feedback being provided to the user.
    #
    def __init__(self, *args, **kwargs):
        self.audiolog_dir = paths.sub("audiolog")
        self.audiolog_db = os.path.join(self.audiolog_dir, "audiolog.db")
        self.keywords = [keyword.upper() for keyword in profile.get(['keyword'], ['NAOMI'])]
        super(Pocketsphinx_KWS_Train, self).__init__(*args, **kwargs)

    # command allows the output to split into stages, and description allows
    # a description to be passed in with the incoming command.
    # If the nextcommand is the empty string, then the program concludes.
    def HandleCommand(self, command, description):
        response = []
        nextcommand = ""
        continue_next = True
        try:
            conn = sqlite3.connect(self.audiolog_db)
            c = conn.cursor()
            if command == "":
                query = " ".join([
                    "select distinct filename",
                    "from audiolog",
                    "where transcription like '%{}%'",
                    "   and type in ('active','passive')"
                ]).format("%' or transcription like '%".join(self.keywords))
                c.execute(query)
                heard=c.fetchall()
                response.append("""<p>Heard keyword</p>""")
                for filename in heard:
                    response.append("""{}""".format(filename[0]))
                query = " ".join([
                    "select distinct filename",
                    "from audiolog",
                    "where verified_transcription like '%{}%'"
                ]).format("%' or transcription like '%".join(self.keywords))
                c.execute(query)
                said=c.fetchall()
                response.append("""<p>Said keyword</p>""")
                for filename in said:
                    response.append("""{}""".format(filename[0]))
                nextcommand = ""
                description.append("Finish")
        except Exception as e:
            continue_next = False
            message = "Unknown"
            if hasattr(e, "message"):
                message = e.message
            self._logger.error(
                "Error: {}".format(
                    message
                ),
                exc_info=True
            )
            response.append('<span class="failure">{}</span>'.format(
                message
            ))
        if not continue_next:
            nextcommand = ""
        return response, nextcommand, description
