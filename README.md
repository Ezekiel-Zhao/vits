*2023/Oct/20*\
This repository is a reimplementation of the code for the paper titled 'Transfer Learning Framework for Low-Resource Text-to-Speech using a Large-Scale Unlabeled Speech Corpus' created in response to the original paper's lack of provided code for the discussed method. \
See the link https://doi.org/10.48550/arXiv.2203.15447

**Methodology** \
Aims to equip VITS with self-supervised learning capability.\
Idea: This is achieved by applying a K-means codebook to the Wave2Vec2 hidden states, creating a pseudo-phoneme to replace the phoneme input in VITS. Additionally, we added two extra parts: Pre-training & Fine-Tuning. \
Pretraining stage: All parameters are trainable (excluding Wave2vec2), while the Duration Predictor is not included in the pre-training part.\
Fine-Tuning stage: Training is required for FLOW, Decoder, and the reference encoder.\
Prediction stage: Identical to VITS.
More details will be updated later.


*Due to the intensive workload in university, This repo will be updated per week or two weeks.* 

*2023/Nov/10* \
Simplified Attemtion, see First Try folder: \
Attempted to use Wave2vec2 in Dataloader to assess whether the original idea is feasible. However, after completing the code, an issue was discovered: It failed to utilize multi-processor, num_worker cannot be > 0. It seems I should find a way to combine Wave2vec2 with the model.

*2023/Nov/12* \
Determined the new direction: \
Edited Dataset and Dataloader to fit the pre-training and fine-tuning mode. \
Used Wave2Vec2 latent representation + K-Means as pseudo-phoneme.

*2023/Nov/16* \
Edited Models.py, completed the pseudo phoneme extraction part, and finished Pseudo_Text_Encoder.

*2023/Nov/22* \
Edited SynthesizerTrn to phoneme_SynthesizerTrn, determinded which part of original code needed to be edited.\
In Train.py: net_g, train_and_evaluate method, and need to create pre-training, fine-tuning part.

*2023/Nov/29* \
Pre-training procedure is added, however, identified a few bugs in SynthesizerTrn, which need to be fixed.

*2023/Nov/30* \
Bugs are caused by the training device, as my code was tested using a CPU, not a GPU.

*2023/Dec/5* \
Pre-training part is almost complete. Tested on the LJ Speech dataset, the loss appears satisfactory. The fine-tuning and inference will be added soon.

