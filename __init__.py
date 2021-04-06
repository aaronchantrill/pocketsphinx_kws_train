# -*- coding: utf-8 -*-
import logging
import os
import re
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
        self.hmm_dir = profile.get(['pocketsphinx', 'hmm_dir'])
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
        self._vocabulary_name = 'pocketsphinx_kws'

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
    def HandleCommand(self, **kwargs):
        command = kwargs['command']
        description = kwargs['description']
        conn = kwargs['conn']
        best = 0
        response = []
        nextcommand = ""
        continue_next = True
        try:
            conn.execute(" ".join([
                "create table if not exists pocketsphinx_kws_temp(",
                "   keyword,",
                "   threshold,",
                "   precision,",
                "   recall,",
                "   f1",
                ")"
            ]))
            conn.commit()
            if(command == ""):
                command = "step:-10:10:1:20:-10"
                response.append("<pre>-----------------------------------------------------------------------------------------------------</pre>")
                response.append("<pre>|{:10s}|{:10s}|{:10s}|{:10s}|{:10s}|{:10s}|{:10s}|{:10s}|{:10s}|</pre>".format(
                    "Keyword",
                    "Theshold",
                    "Detected",
                    "TP",
                    "FP",
                    "FN",
                    "Precision",
                    "Recall",
                    "F1"
                ))
                response.append("<pre>-----------------------------------------------------------------------------------------------------</pre>")
                conn.execute("delete from pocketsphinx_kws_temp")
                conn.commit()
            if(command[:4] == "step"):
                # step:[start]:[end]:[stepsize]:[samples]:[step]
                params = re.search(r"^step:([-\d]+):([-\d]+):([-\d]+):([-\d]+):([-\d]+)$", command)
                start = int(params[1])
                end = int(params[2])
                stepsize = int(params[3])
                samples = int(params[4])
                step = int(params[5])
                if(step < end):
                    nextcommand = "step:{}:{}:{}:{}:{}".format(start, end, stepsize, samples, step + stepsize)
                else:
                    nextcommand = "finish"
                # compile the keywords into a dictionary
                language = profile.get(['language'], 'en-US')
                vocabulary = vocabcompiler.VocabularyCompiler(
                    self.info.name,
                    self._vocabulary_name,
                    path=paths.sub('vocabularies', language)
                )
                # The threshold should be between 1 and 50. Run with 1 first and
                # get a matrix of true positives, false positives, true negatives
                # and false negatives. If the audio contains the word "Naomi" then
                # the word "Naomi" should appear in the verified transcription.
                # If the type is unclear or noise, then there should not be anything
                # in the verified transcription
                threshold = step
                for keyword in self.keywords:
                    keyword = keyword.upper()
                    # Get a list of all records to tested. This includes records of type
                    # active, passive, noise and unclear (noise and unclear are assumed not
                    # to contain the word "Naomi"
                    query = " ".join([
                        "select *",
                        "from(",
                        "    select distinct ",
                        "        filename,verified_transcription",
                        "    from audiolog",
                        "    where reviewed > ''",
                        "        and verified_transcription like '%", keyword, "%'",
                        "    limit {}".format(samples / 2),
                        ")a",
                        "union select * ",
                        "from(",
                        "    select distinct ",
                        "        filename, verified_transcription",
                        "    from audiolog",
                        "    where reviewed > ''",
                        "        and transcription like '%", keyword, "%'",
                        "        and verified_transcription not like '%", keyword, "%'",
                        "    limit {})".format(samples / 2),
                        "b;"
                    ])
                    print("Selecting examples")
                    print(query)
                    test_data = conn.execute(query).fetchall()
                    print(test_data)
                    total_instances = 0
                    total_detected = 0
                    false_positives = 0
                    false_negatives = 0
                    true_positives = 0
                    precision = 0
                    recall = 0
                    f1 = 0
                    self._logger.debug(keyword)
                    # create a dictionary for the keyword
                    vocabulary.compile(
                        sphinxvocab.compile_vocabulary,
                        [keyword]
                    )
                    dict_path = sphinxvocab.get_dictionary_path(vocabulary.path)
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
                    config.set_string('-hmm', self.hmm_dir)
                    config.set_string('-keyphrase', keyword)
                    if(threshold < 0):
                        config.set_float('-kws_threshold', eval("1e-{}".format(-threshold)))
                    else:
                        config.set_float('-kws_threshold', eval("1e+{}".format(threshold)))
                    config.set_string('-dict', dict_path)
                    decoder = pocketsphinx.Decoder(config)
                    # Now we have the decoder configured at the current level
                    # Run through the data
                    for index in range(len(test_data)):
                        recording = test_data[index]
                        print("{} {} {}/{}".format(keyword, threshold, index, len(test_data)))
                        print(recording)
                        filename, transcript = recording
                        transcript = transcript.upper()
                        # Check how many times the keyphrase actually appears in the transcript
                        transcript_count = transcript.count(keyword)
                        decoder_count = 0
                        print(os.path.join(self.audiolog_dir, filename))
                        with open(os.path.join(self.audiolog_dir, filename), "r+b") as fp:
                            fp.seek(44)
                            audio_data = fp.read()
                            decoder.start_utt()
                            decoder.process_raw(audio_data, False, True)
                            decoder.end_utt()
                            for s in decoder.seg():
                                if(s.word == keyword):
                                    decoder_count += 1
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
                        print(
                            "{}: {}/{} ({})".format(
                                transcript,
                                decoder_count,
                                transcript_count,
                                total_instances
                            )
                        )
                        if decoder_count < transcript_count:
                            false_negatives += transcript_count - decoder_count
                            true_positives += decoder_count
                        else:
                            false_positives += decoder_count - transcript_count
                            true_positives += transcript_count
                        precision = 0
                        if(true_positives + false_positives > 0):
                            precision = true_positives/(true_positives+false_positives)
                        recall = 0
                        if(true_positives + false_negatives > 0):
                            recall = true_positives/(true_positives+false_negatives)
                        f1 = 0
                        if(precision+recall > 0):
                            f1 = 2*(precision*recall/(precision+recall))
                        # print("Instances: {} TP: {} FP: {} FN: {} Precision: {} Recall: {} F1: {}".format(
                        #    total_instances,
                        #    true_positives,
                        #    false_positives,
                        #    false_negatives,
                        #    precision,
                        #    recall,
                        #    f1
                        # ))
                    conn.execute(
                        "insert into pocketsphinx_kws_temp(keyword, threshold, precision, recall, f1)values(?, ?, ?, ?, ?)", (
                            keyword, threshold, precision, recall, f1
                        )
                    )
                    conn.commit()
                    response.append("<pre>|{:10s}|{:10d}|{:10s}|{:10d}|{:10d}|{:10d}|{:10.3f}|{:10.3f}|{:10.3f}|</pre>".format(
                        keyword,
                        threshold,
                        str(total_detected)+"/"+str(total_instances),
                        true_positives,
                        false_positives,
                        false_negatives,
                        precision,
                        recall,
                        f1
                    ))
                    maxf1 = conn.execute("select max(f1) from pocketsphinx_kws_temp").fetchone()[0]
                    print("Max(f1) = {}".format(maxf1))
                    if(maxf1 > f1):
                        countmax = conn.execute(
                            " ".join([
                                "select count(*)",
                                "from pocketsphinx_kws_temp",
                                "where f1 = {}".format(maxf1)
                            ])
                        ).fetchone()[0]
                        start = conn.execute(
                            " ".join([
                                "select case",
                                "   when exists(",
                                "       select 1",
                                "       from pocketsphinx_kws_temp",
                                "       where threshold < (",
                                "           select min(threshold)",
                                "           from pocketsphinx_kws_temp",
                                "           where f1=(",
                                "               select max(f1)",
                                "               from pocketsphinx_kws_temp",
                                "           )",
                                "       )",
                                "   ) then (",
                                "       select max(threshold)",
                                "       from pocketsphinx_kws_temp",
                                "       where threshold < (",
                                "           select min(threshold)",
                                "           from pocketsphinx_kws_temp",
                                "           where f1=(",
                                "               select max(f1)",
                                "               from pocketsphinx_kws_temp",
                                "           )",
                                "       )",
                                "   ) else (",
                                "       select min(threshold)",
                                "       from pocketsphinx_kws_temp",
                                "   )",
                                "end"
                            ])
                        ).fetchone()[0]
                        end = threshold
                        if(countmax == 1):
                            # We have identified our best match
                            best = start
                            command = "finish"
                        else:
                            # if the number is starting to fall, then we have
                            # passed the peak and there is no point continuing
                            if(samples < 100):
                                # clear the database
                                conn.execute("delete from pocketsphinx_kws_temp")
                                conn.commit()
                                # Test the best range again by increasing the
                                # number of samples
                                samples = samples * 2
                                nextcommand = "step:{}:{}:{}:{}:{}".format(
                                    start,
                                    end,
                                    stepsize,
                                    samples,
                                    start
                                )
                            else:
                                continue_next = False
                                command = "finish"
                                best = conn.execute(
                                    " ".join([
                                        "select min(threshold)",
                                        "from pocketsphinx_kws_temp",
                                        "where f1=(",
                                        "   select max(f1)",
                                        "   from pocketsphinx_kws_temp",
                                        ")"
                                    ])
                                ).fetchone()[0]
            if(command == "finish"):
                response.append("<pre>-----------------------------------------------------------------------------------------------------</pre>")
                response.append("Best threshold: {}".format(best))
                profile.set_profile_var(['pocketsphinx_kws', 'threshold'], best)
                profile.save_profile()
                continue_next = False
            else:
                print("Command: {}".format(command))
            print("\n".join(response))
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
            response.append(
                '<span class="failure">{}</span>'.format(
                    message
                )
            )
        if not continue_next:
            nextcommand = ""
        return response, nextcommand, description
