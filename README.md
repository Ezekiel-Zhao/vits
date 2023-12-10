*2023/Oct/20*\
This repository is a reimplementation of the code for the paper titled 'Transfer Learning Framework for Low-Resource Text-to-Speech using a Large-Scale Unlabeled Speech Corpus' created in response to the original paper's lack of provided code for the discussed method. \
See the link https://doi.org/10.48550/arXiv.2203.15447

**Methodology** \
Aims to equip VITS with self-supervised learning capability.\
Idea: This is achieved by applying a K-means codebook to the Wave2Vec2 hidden states, creating a pseudo-phoneme to replace the phoneme input in VITS. Additionally, we added two extra parts: Pre-training & Fine-Tuning. \
Pretraining stage: All parameters are trainable (excluding Wave2vec2), while the Duration Predictor is not included in the pre-training part.\
Fine-Tuning stage: Training is required for FLOW, Decoder, and the reference encoder.\
Prediction stage: Identical to VITS.\
More details will be updated later.

![image text](https://github.com/Ezekiel-Zhao/vits/blob/main/Img_folder/model.png)

**How to use this repo** \
Notice, the speech dataset should has sampling rate = 16000.
1. Pre-training & Fine-Tuning Part: \
  See Second_Try/configs/ljs_base.json, set training_mode.mode = "pre-training" or "fine-tuning", and all is done!
2. The classes I wrote in models.py: \
   *psudo_phoneme*: input as audio-waves, output as the pseudo-phoneme, output example: [0, 12, 0, 14, 0, 120, 0, 42] the pseduo phoneme for "I love you".\
   *pseudo_text_encoder*: the pseudo-phoneme encoder. \
   *phoneme_SynthesizerTrn*: The generator for the pre-training procedure. The method infer_pre_training in this class, gives a way to test this generator. \
   *SynthesizerTrn*: I edited this to fit the fine-tuning mode. 

   In train.py & data_utils.py:\
   train_and_evaluate_fine_tuning & train_and_evaluate_pre_training method is added.\
   specify the training_mode in the configuration to load (text, vocie_wave, spec) or (voice_wave, spec).

3. text_phoneme.ipynb, if you want test the class *psudo_phoneme*. 
4. inference.ipynb, after finish the fine-tuning, you can test the performance here.



**However, there is one thing I need to mention**\
Due to GPU computation constraints, I was only able to complete 6 epochs of pre-training, which required approximately 30 hours on a GTX 3090 with a batch size of 10. This process exhibited a convergence trend closely resembling that of the original VITS, suggesting that the training procedure was correctly implemented. \

When testing a voice clip using the pre-trained model, I was able to roughly discern tone and content in the output. This test aimed to verify if the model had learned anything during the pre-training phase. It's important to note that the duration predictor wasn't trained during pre-training, so I didn't anticipate passing results using only the duration predictor with its initialized parameters.\

Following this, I fine-tuned the model on a subset of the LJ Speech dataset. The loss showed a decreasing trend, indicating that the model was improving. Considering the incomplete training of the pre-training model, my primary goal was to ensure that the fine-tuning process was functioning correctly. \



*Due to the intensive workload in university, This repo will be updated per week or two weeks.* 

**Time Line** 

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

*2023/Dec/8* \
Fine-tuning part is finished, the model is training, I will update the code very soon.

*2023/Dec/10* \
Code is updated. Instructions about how to train the model is also updated. \
