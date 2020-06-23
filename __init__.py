# -*- coding: utf-8 -*-
import logging
import os
import sqlite3
from naomi import paths
from naomi import plugin
from naomi import profile
from naomi import vocabcompiler
from . import sphinxvocab 
try:
    try:
        from pocketsphinx import pocketsphinx
    except ValueError:
        # Fixes a quirky bug when first import doesn't work.
        # See http://sourceforge.net/p/cmusphinx/bugs/284/ for details.
        from pocketsphinx import pocketsphinx
    pocketsphinx_available = True
    # Why do we have to import sphinxbase.sphinxbase.*?
    # otherwise, when we create pocketsphinx.Decoder.default_config()
    # we get the wrong object for some reason.
    from sphinxbase.sphinxbase import *
except ImportError:
    pocketsphinx = None
    pocketsphinx_available = False
from .g2p import PhonetisaurusG2P

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
    def __init__(self, *args, **kwargs):
        super(Pocketsphinx_KWS_Train, self).__init__(*args, **kwargs)
        self.audiolog_dir = paths.sub("audiolog")
        self.audiolog_db = os.path.join(self.audiolog_dir, "audiolog.db")
        self.keywords = [keyword.upper() for keyword in profile.get(['keyword'], ['NAOMI'])]
        self._logger = logging.getLogger(__name__)
        self.executable = profile.get(
            ['pocketsphinx', 'phonetisaurus_executable'],
            'phonetisaurus-g2p'
        )
        self.nbest = profile.get(
            ['pocketsphinx', 'nbest'],
            3
        )
        self.fst_model = profile.get(['pocketsphinx', 'fst_model'])
        self.fst_model_alphabet = profile.get(
            ['pocketsphinx', 'fst_model_alphabet'],
            'arpabet'
        )
        self.g2pconverter = PhonetisaurusG2P(
            self.executable,
            self.fst_model,
            fst_model_alphabet=self.fst_model_alphabet,
            nbest=self.nbest
        )
        self._vocabulary_name='pocketsphinx_kws'

        """
        Initiates the pocketsphinx instance.

        Arguments:
            vocabulary -- a PocketsphinxVocabulary instance
            hmm_dir -- the path of the Hidden Markov Model (HMM)
        """

        if not pocketsphinx_available:
            raise ImportError("Pocketsphinx not installed!")


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
            if(command==""):
                command="step1"
            if(command[:4]=="step"):
                step = eval(command[4:])
                if(step<50):
                    nextcommand="step{}".format(step+1)
                else:
                    nextcommand="finish"
                # compile the keywords into a dictionary
                language = profile.get(['language'], 'en-US')

                vocabulary = vocabcompiler.VocabularyCompiler(
                    self.info.name,
                    self._vocabulary_name,
                    path=paths.sub('vocabularies', language)
                )

                vocabulary.compile(
                    vocabulary,
                    self.keywords
                )

                # Get a list of all records to tested. This includes records of type
                # active, passive, noise and unclear (noise and unclear are assumed not
                # to contain the word "Naomi"
                query = " ".join([
                    "select distinct",
                    " filename,",
                    " transcription,",
                    " verified_transcription",
                    "from audiolog"
                ])
                c.execute(query)
                test_data = c.fetchall()
                # The threshold should be between 1 and 50. Run with 1 first and
                # get a matrix of true positives, false positives, true negatives
                # and false negatives. If the audio contains the word "Naomi" then
                # the word "Naomi" should appear in the verified transcription.
                # If the type is unclear or noise, then there should not be anything
                # in the verified transcription
                threshold=step
                for keyword in self.keywords:
                    false_positives = 0
                    false_negatives = 0
                    true_positives = 0
                    total_instances = 0
                    total_detected = 0
                    self._logger.debug(keyword)
                    self._logger.debug(
                        ("%s --model=%s --beam=1000 --thresh=99.0 --accumulate=true " +
                        "--pmass=0.85 --nlog_probs=false --wordlist=%s --nbest=%d") %
                        (self.executable, self.fst_model, tmp_fname, self.nbest)
                    )
                    # create a dictionary for the keyword
                    output = execute(
                        self.executable,
                        self.fst_model,
                        tmp_fname,
                        is_file=True,
                        nbest=self.nbest
                    )
                    # speech = AudioFile(
                    #     lm=False,
                    #     audio_file='/home/pi/.config/naomi/audiolog/2020-06-19_05-36-28k9zu8zyy.wav',
                    #     keyphrase="NAOMI",
                    #     kws_threshold=1e-20,
                    #     hmm='/home/pi/.config/naomi/pocketsphinx/standard/en-US',
                    #     dict='/home/pi/.config/naomi/vocabularies/en-US/sphinx/keyword/dictionary'
                    # )
                    # Pocketsphinx v5
                    config = pocketsphinx.Decoder.default_config()
                    config.set_string('-hmm', hmm_dir)
                    config.set_string('-keyphrase', keyword)
                    config.set_float('-kws_threshold', eval("1e+{}".format(threshold)))
                    config.set_string('-dict', dict_path)
                    config.set_string('-logfn', self._logger)
                    self._decoder = pocketsphinx.Decoder(config)
                    # Now we have the decoder configured at the current level
                    # Run through the data
                    for recording in test_data:
                        filename, transcript=recording
                        transcript=upper(transcript)
                        # Check how many times the keyphrase actually appears in the transcript
                        transcript_count = transcript.count(keyword)
                        decoder_count = 0
                        with open(filename, "r+b") as fp:
                            fp.seek(44)
                            audio_data=fp.read()
                            decoder.start_utt()
                            decoder.process_raw(fp)
                            decoder.end_utt()
                            for s in decoder.seg():
                                if(s.word==keyword):
                                    decoder_count+=1
                        # so if decoder_count < transcript_count, then we assume
                        # transcript_count-decoder_count instances got missed
                        # (false negative)
                        # if transcript_count < decoder_count, then we assume
                        # decoder_count - transcript_count instances should
                        # not have been detected
                        # (false positive)
                        # It is, of course, possible that both things have
                        # happened and that a word is misidentified in the
                        # wrong place, but we'll assume not.
                        total_instances += transcript_count
                        total_detected += decoder_count
                        if decoder_count < transcript_count:
                            false_negatives += transcript_count - decoder_count
                            true_positives += decoder_count
                        else:
                            false_positives += decoder_count - transcript_count
                            true_positives += transcript_count
                print("Keyword: {}".format(keyword))
                print("Threshold: {}".format(threshold))
                print("Correct: {}".format(correct))
                print("False positives: {}".format(false_positives))
                print("False negatives: {}".format(false_negatives))
                print("Precision: {}".format(true_positives/total_detected))
                print("Recall: {}".format(true_positives/total_instances))
                print()
            else:
                print("Command: {}".format(command))
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
