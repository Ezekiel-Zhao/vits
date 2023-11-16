*2023/Oct/20
This repo aims to equip VITS with self-supervised learning ability. \
Trying to combine VITS with Wave2Vec2.0, most of the code will based on VITS.\
The original idea: Trying to using wave2vec2 to generate phonemes from audiowave, to replace the word preprocess part of VITS.\
Pretraining stage: all parameters are trainable (Wave2vec2 not included)\
Fine-Tuning stage: Perhaps only train FLOW part is enough? (Wait to try)\
Prediction stage: The same as VITS.\
More detailed will be updated later.\

*Due to the intensive workload in university, This repo will be updated per week or two weeks. 

*2023/Nov/10* \
Simplified Attemtion, see First Try folder: \
Tried to use Wave2vec2 in Dataloader to try whether the original idea is make sense, however, after finised the code, one issue was found: It failed to use multi-processer, num_worker can not > 0. Seems like I should find a way to combine Wave2vec2 with the text decoder.

*2023/Nov/12* \
Find the new way: \
Edited Dataset and Dataloader, so that fit the pre-training and fine-tuning mode.\
Use Wave2Vec2 latent representation + K-Means as psedo-phoneme.

*2023/Nov/16* \
Edited Models.py, finish pseudo phoneme extraction part, and finish a part of Pseudi-Text-Encoder.
