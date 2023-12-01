*2023/Oct/20*\
This repository is a reimplementation of the code for the paper titled 'Transfer Learning Framework for Low-Resource Text-to-Speech using a Large-Scale Unlabeled Speech Corpus' created in response to the original paper's lack of provided code for the discussed method. \
See the link https://doi.org/10.48550/arXiv.2203.15447

**Methdology** \
Aims to equip VITS with self-supervised learning ability. \
Idea: This is being achieved by applying a K-means codebook to the Wave2Vec2 hidden states, creating a pseudo-phoneme to replace the phoneme input in VITS. Meanwhile, we added extra two parts: Pre-training & Fine-Tuning. \
Pretraining stage: All parameters are trainable (Wave2vec2 not included).\
Fine-Tuning stage: Only train FLOW part is enough. \
Prediction stage: The same as VITS.\
More detailed will be updated later.


*Due to the intensive workload in university, This repo will be updated per week or two weeks.* 

*2023/Nov/10* \
Simplified Attemtion, see First Try folder: \
Tried to use Wave2vec2 in Dataloader to try whether the original idea is make sense, however, after finised the code, one issue was found: It failed to use multi-processer, num_worker can not > 0. Seems like I should find a way to combine Wave2vec2 with the text decoder.

*2023/Nov/12* \
Find the new way: \
Edited Dataset and Dataloader, so that fit the pre-training and fine-tuning mode.\
Use Wave2Vec2 latent representation + K-Means as psedo-phoneme.

*2023/Nov/16* \
Edited Models.py, finish pseudo phoneme extraction part, and finished Pseudo_Text_Encoder.

*2023/Nov/22* \
Edited SynthesizerTrn to phoneme_SynthesizerTrn, determinded which part of original code needed to be edited.\
In Train.py: net_g, train_and_evaluate method, and need to create pre-training, fine-tuning part.

*2023/Nov/29* \
Pre-training procedure is added, however, identified few bugs in Syr, needed to be fixed.

*2023/Nov/30* \
Bugs are caused by training device, since my code were testing use CPU, not GPU.
