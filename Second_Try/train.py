import os
import json
import argparse
import itertools
import math
import torch
from torch import nn, optim
from torch.nn import functional as F
from torch.utils.data import DataLoader
from torch.utils.tensorboard import SummaryWriter
import torch.multiprocessing as mp
import torch.distributed as dist
from torch.nn.parallel import DistributedDataParallel as DDP
from torch.cuda.amp import autocast, GradScaler
import numpy as np
from sklearn.cluster import KMeans

import commons
import utils
from data_utils import (
  TextAudioLoader,
  TextAudioCollate,
  DistributedBucketSampler
)
from models import (
  SynthesizerTrn,
  phoneme_SynthesizerTrn,
  MultiPeriodDiscriminator,
  psudo_phoneme,
)
from losses import (
  generator_loss,
  discriminator_loss,
  feature_loss,
  kl_loss
)
from mel_processing import mel_spectrogram_torch, spec_to_mel_torch
from text.symbols import symbols


torch.backends.cudnn.benchmark = True
global_step = 0


def main():
  """Assume Single Node Multi GPUs Training Only"""
  assert torch.cuda.is_available(), "CPU training is not allowed."

  n_gpus = torch.cuda.device_count()
  os.environ['MASTER_ADDR'] = 'localhost'
  os.environ['MASTER_PORT'] = '65535'

  hps = utils.get_hparams()
  mp.spawn(run, nprocs=n_gpus, args=(n_gpus, hps,))


def run(rank, n_gpus, hps, mode = 'pre-training'):
  '''
  add mode to run function, to distinguish between pre-training and fine-tuning.

  '''
  global global_step
  if rank == 0:
    logger = utils.get_logger(hps.model_dir)
    logger.info(hps)
    utils.check_git_hash(hps.model_dir)
    writer = SummaryWriter(log_dir=hps.model_dir)
    writer_eval = SummaryWriter(log_dir=os.path.join(hps.model_dir, "eval"))

  dist.init_process_group(backend='nccl', init_method='env://', world_size=n_gpus, rank=rank)
  torch.manual_seed(hps.train.seed)
  torch.cuda.set_device(rank)

  train_dataset = TextAudioLoader(hps.data.training_files, hps.data, mode)
  train_sampler = DistributedBucketSampler(
      train_dataset,
      hps.train.batch_size,
      [32,300,400,500,600,700,800,900,1000],
      num_replicas=n_gpus,
      rank=rank,
      shuffle=True)
  collate_fn = TextAudioCollate(mode=mode)
  train_loader = DataLoader(train_dataset, num_workers=8, shuffle=False, pin_memory=True,
      collate_fn=collate_fn, batch_sampler=train_sampler)
  
  # Apply Wave2vec2 to all audio wave
  psudo_phoneme_instance = psudo_phoneme()
  processor = psudo_phoneme_instance.processor
  model = psudo_phoneme_instance.model
  outputs = []
  with torch.no_grad():
      for batch in train_loader:
        input_values = processor(batch, return_tensors="pt", padding=True, sampling_rate=16000).input_values.squeeze(0)
        output = model(input_values)
        hidden_representations = outputs.last_hidden_state
        outputs.append(hidden_representations.reshape(-1, 768).cpu().numpy())
  
  # Codebook generation
  codebook = KMeans(n_clusters=128, random_state=0).fit(outputs)


  if rank == 0:
    eval_dataset = TextAudioLoader(hps.data.validation_files, hps.data, mode)
    eval_loader = DataLoader(eval_dataset, num_workers=8, shuffle=False,
        batch_size=hps.train.batch_size, pin_memory=True,
        drop_last=False, collate_fn=collate_fn)

  # based on training mode to change generator network.  
  if hps.training_mode.mode == 'pre-training':
    net_g = phoneme_SynthesizerTrn(
      codebook,
      len(symbols),
      hps.data.filter_length // 2 + 1,
      hps.train.segment_size // hps.data.hop_length,
      **hps.model).cuda(rank)
  else:
    net_g = SynthesizerTrn(
      len(symbols),
      hps.data.filter_length // 2 + 1,
      hps.train.segment_size // hps.data.hop_length,
      **hps.model).cuda(rank)
 
  net_d = MultiPeriodDiscriminator(hps.model.use_spectral_norm).cuda(rank)
  optim_g = torch.optim.AdamW(
      net_g.parameters(), 
      hps.train.learning_rate, 
      betas=hps.train.betas, 
      eps=hps.train.eps)
  optim_d = torch.optim.AdamW(
      net_d.parameters(),
      hps.train.learning_rate, 
      betas=hps.train.betas, 
      eps=hps.train.eps)
  net_g = DDP(net_g, device_ids=[rank])
  net_d = DDP(net_d, device_ids=[rank])

  if hps.training_mode.mode == 'pre-training':
    try:
      _, _, _, epoch_str = utils.load_checkpoint(utils.latest_checkpoint_path(hps.model_dir, "G_*.pth"), net_g, optim_g)
      _, _, _, epoch_str = utils.load_checkpoint(utils.latest_checkpoint_path(hps.model_dir, "D_*.pth"), net_d, optim_d)
      global_step = (epoch_str - 1) * len(train_loader)
    except:
      epoch_str = 1
      global_step = 0
    
  else:
    try:
      _, _, _, epoch_str = utils.load_checkpoint(utils.latest_checkpoint_path(hps.model_dir, "G_*.pth"), net_g, optim_g)
      _, _, _, epoch_str = utils.load_checkpoint(utils.latest_checkpoint_path(hps.model_dir, "D_*.pth"), net_d, optim_d)
      global_step = (epoch_str - 1) * len(train_loader)
    except:
      epoch_str = 1
      global_step = 0

  scheduler_g = torch.optim.lr_scheduler.ExponentialLR(optim_g, gamma=hps.train.lr_decay, last_epoch=epoch_str-2)
  scheduler_d = torch.optim.lr_scheduler.ExponentialLR(optim_d, gamma=hps.train.lr_decay, last_epoch=epoch_str-2)

  scaler = GradScaler(enabled=hps.train.fp16_run)

  for epoch in range(epoch_str, hps.train.epochs + 1):
    
    if rank==0:
      if hps.training_mode.mode == 'pre-training':
        train_and_evaluate_pre_training(rank, epoch, hps, [net_g, net_d], [optim_g, optim_d], 
                                        [scheduler_g, scheduler_d], scaler, [train_loader, eval_loader], logger, [writer, writer_eval])
      else:
        train_and_evaluate_fine_tuning(rank, epoch, hps, [net_g, net_d], [optim_g, optim_d],
                                       [scheduler_g, scheduler_d], scaler, [train_loader, eval_loader], logger, [writer, writer_eval])
        
    else:
        if hps.training_mode.mode == 'pre-training':
          train_and_evaluate_pre_training(rank, epoch, hps, [net_g, net_d], [optim_g, optim_d], 
                                          [scheduler_g, scheduler_d], scaler, [train_loader, None], None, None)
        else:
          train_and_evaluate_fine_tuning(rank, epoch, hps, [net_g, net_d], [optim_g, optim_d], 
                                         [scheduler_g, scheduler_d], scaler, [train_loader, None], None, None)
          
    scheduler_g.step()
    scheduler_d.step()

 
def train_and_evaluate_pre_training(rank, epoch, hps, nets, optims, schedulers, scaler, loaders, logger, writers, mode = 'pre-training'):
  net_g, net_d = nets
  optim_g, optim_d = optims
  scheduler_g, scheduler_d = schedulers
  train_loader, eval_loader = loaders
  if writers is not None:
    writer, writer_eval = writers

  train_loader.batch_sampler.set_epoch(epoch)
  global global_step

  net_g.train()
  net_d.train()
  for batch_idx, (spec, spec_lengths, y, y_lengths) in enumerate(train_loader): #y = wave
      spec, spec_lengths = spec.cuda(rank, non_blocking=True), spec_lengths.cuda(rank, non_blocking=True)
      y, y_lengths = y.cuda(rank, non_blocking=True), y_lengths.cuda(rank, non_blocking=True)

      with autocast(enabled=hps.train.fp16_run):
        y_hat, l_length, attn, ids_slice, x_mask, z_mask,\
        (z, z_p, m_p, logs_p, m_q, logs_q) = net_g(y, y_lengths, spec, spec_lengths)

        mel = spec_to_mel_torch(
            spec, 
            hps.data.filter_length, 
            hps.data.n_mel_channels, 
            hps.data.sampling_rate,
            hps.data.mel_fmin, 
            hps.data.mel_fmax)
        y_mel = commons.slice_segments(mel, ids_slice, hps.train.segment_size // hps.data.hop_length)
        y_hat_mel = mel_spectrogram_torch(
            y_hat.squeeze(1), 
            hps.data.filter_length, 
            hps.data.n_mel_channels, 
            hps.data.sampling_rate, 
            hps.data.hop_length, 
            hps.data.win_length, 
            hps.data.mel_fmin, 
            hps.data.mel_fmax
        )

        y = commons.slice_segments(y, ids_slice * hps.data.hop_length, hps.train.segment_size) # slice 

        # Discriminator
        y_d_hat_r, y_d_hat_g, _, _ = net_d(y, y_hat.detach())
        with autocast(enabled=False):
          loss_disc, losses_disc_r, losses_disc_g = discriminator_loss(y_d_hat_r, y_d_hat_g)
          loss_disc_all = loss_disc
      optim_d.zero_grad()
      scaler.scale(loss_disc_all).backward()
      scaler.unscale_(optim_d)
      grad_norm_d = commons.clip_grad_value_(net_d.parameters(), None)
      scaler.step(optim_d)

      with autocast(enabled=hps.train.fp16_run):
        # Generator
        y_d_hat_r, y_d_hat_g, fmap_r, fmap_g = net_d(y, y_hat)
        with autocast(enabled=False):
          #loss_dur = torch.sum(l_length.float()) 
          # Duration predictor is not included in this process
          loss_mel = F.l1_loss(y_mel, y_hat_mel) * hps.train.c_mel
          loss_kl = kl_loss(z_p, logs_q, m_p, logs_p, z_mask) * hps.train.c_kl

          loss_fm = feature_loss(fmap_r, fmap_g)
          loss_gen, losses_gen = generator_loss(y_d_hat_g)
          loss_gen_all = loss_gen + loss_fm + loss_mel + loss_kl
      optim_g.zero_grad()
      scaler.scale(loss_gen_all).backward()
      scaler.unscale_(optim_g)
      grad_norm_g = commons.clip_grad_value_(net_g.parameters(), None)
      scaler.step(optim_g)
      scaler.update()

      if rank==0:
        if global_step % hps.train.log_interval == 0:
          lr = optim_g.param_groups[0]['lr']
          losses = [loss_disc, loss_gen, loss_fm, loss_mel, loss_kl]
          logger.info('Train Epoch: {} [{:.0f}%]'.format(
            epoch,
            100. * batch_idx / len(train_loader)))
          logger.info([x.item() for x in losses] + [global_step, lr])
          
          scalar_dict = {"loss/g/total": loss_gen_all, "loss/d/total": loss_disc_all, "learning_rate": lr, "grad_norm_d": grad_norm_d, "grad_norm_g": grad_norm_g}
          scalar_dict.update({"loss/g/fm": loss_fm, "loss/g/mel": loss_mel, "loss/g/kl": loss_kl})

          scalar_dict.update({"loss/g/{}".format(i): v for i, v in enumerate(losses_gen)})
          scalar_dict.update({"loss/d_r/{}".format(i): v for i, v in enumerate(losses_disc_r)})
          scalar_dict.update({"loss/d_g/{}".format(i): v for i, v in enumerate(losses_disc_g)})
          image_dict = { 
              "slice/mel_org": utils.plot_spectrogram_to_numpy(y_mel[0].data.cpu().numpy()),
              "slice/mel_gen": utils.plot_spectrogram_to_numpy(y_hat_mel[0].data.cpu().numpy()), 
              "all/mel": utils.plot_spectrogram_to_numpy(mel[0].data.cpu().numpy()),
              "all/attn": utils.plot_alignment_to_numpy(attn[0,0].data.cpu().numpy())
          }
          utils.summarize(
            writer=writer,
            global_step=global_step, 
            images=image_dict,
            scalars=scalar_dict)

        if global_step % hps.train.eval_interval == 0:
          #evaluate(hps, net_g, eval_loader, writer_eval)
          #Evaluation is not included in this process
          utils.save_checkpoint(net_g, optim_g, hps.train.learning_rate, epoch, os.path.join(hps.model_dir, "G_{}.pth".format(global_step)))
          utils.save_checkpoint(net_d, optim_d, hps.train.learning_rate, epoch, os.path.join(hps.model_dir, "D_{}.pth".format(global_step)))
      global_step += 1
  
  if rank == 0:
    logger.info('====> Epoch: {}'.format(epoch))

   
def train_and_evaluate_fine_tuning(rank, epoch, hps, nets, optims, schedulers, scaler, loaders, logger, writers):
  net_g, net_d = nets
  optim_g, optim_d = optims
  scheduler_g, scheduler_d = schedulers
  train_loader, eval_loader = loaders
  if writers is not None:
    writer, writer_eval = writers

  train_loader.batch_sampler.set_epoch(epoch)
  global global_step

  net_g.train()
  #net_d.train()
  for batch_idx, (x, x_lengths, spec, spec_lengths, y, y_lengths) in enumerate(train_loader): 
      x, x_lengths = x.cuda(rank, non_blocking=True), x_lengths.cuda(rank, non_blocking=True)
      spec, spec_lengths = spec.cuda(rank, non_blocking=True), spec_lengths.cuda(rank, non_blocking=True)
      y, y_lengths = y.cuda(rank, non_blocking=True), y_lengths.cuda(rank, non_blocking=True)

      with autocast(enabled=hps.train.fp16_run):
        y_hat, l_length, attn, ids_slice, x_mask, z_mask,\
        (z, z_p, m_p, logs_p, m_q, logs_q) = net_g(x, x_lengths, spec, spec_lengths) #Fine tuning here used real phoneme input

        mel = spec_to_mel_torch(
            spec, 
            hps.data.filter_length, 
            hps.data.n_mel_channels, 
            hps.data.sampling_rate,
            hps.data.mel_fmin, 
            hps.data.mel_fmax)
        y_mel = commons.slice_segments(mel, ids_slice, hps.train.segment_size // hps.data.hop_length)
        y_hat_mel = mel_spectrogram_torch(
            y_hat.squeeze(1), 
            hps.data.filter_length, 
            hps.data.n_mel_channels, 
            hps.data.sampling_rate, 
            hps.data.hop_length, 
            hps.data.win_length, 
            hps.data.mel_fmin, 
            hps.data.mel_fmax
        )

        y = commons.slice_segments(y, ids_slice * hps.data.hop_length, hps.train.segment_size) # slice 

        # Discriminator
        ''' y_d_hat_r, y_d_hat_g, _, _ = net_d(y, y_hat.detach())
        with autocast(enabled=False):
          loss_disc, losses_disc_r, losses_disc_g = discriminator_loss(y_d_hat_r, y_d_hat_g)
          loss_disc_all = loss_disc
      optim_d.zero_grad()
      scaler.scale(loss_disc_all).backward()
      scaler.unscale_(optim_d)
      grad_norm_d = commons.clip_grad_value_(net_d.parameters(), None)
      scaler.step(optim_d)'''

      with autocast(enabled=hps.train.fp16_run):
        # Generator
        #y_d_hat_r, y_d_hat_g, fmap_r, fmap_g = net_d(y, y_hat)
        with autocast(enabled=False):
          loss_dur = torch.sum(l_length.float())
          loss_mel = F.l1_loss(y_mel, y_hat_mel) * hps.train.c_mel
          loss_kl = kl_loss(z_p, logs_q, m_p, logs_p, z_mask) * hps.train.c_kl

          #loss_fm = feature_loss(fmap_r, fmap_g)
          #loss_gen, losses_gen = generator_loss(y_d_hat_g)
          loss_gen_all =  loss_dur + loss_kl + loss_mel
      optim_g.zero_grad()
      scaler.scale(loss_gen_all).backward()
      scaler.unscale_(optim_g)
      grad_norm_g = commons.clip_grad_value_(net_g.parameters(), None)
      scaler.step(optim_g)
      scaler.update()

      if rank==0:
        if global_step % hps.train.log_interval == 0:
          lr = optim_g.param_groups[0]['lr']
          losses = [loss_mel, loss_dur, loss_kl]
          logger.info('Train Epoch: {} [{:.0f}%]'.format(
            epoch,
            100. * batch_idx / len(train_loader)))
          logger.info([x.item() for x in losses] + [global_step, lr])
          
          scalar_dict = {"loss/g/total": loss_gen_all, "learning_rate": lr, "grad_norm_g": grad_norm_g}
          scalar_dict.update({"loss/g/mel": loss_mel, "loss/g/dur": loss_dur, "loss/g/kl": loss_kl})

          #scalar_dict.update({"loss/g/{}".format(i): v for i, v in enumerate(losses_gen)})
          #scalar_dict.update({"loss/d_r/{}".format(i): v for i, v in enumerate(losses_disc_r)})
          #scalar_dict.update({"loss/d_g/{}".format(i): v for i, v in enumerate(losses_disc_g)})
          image_dict = { 
              "slice/mel_org": utils.plot_spectrogram_to_numpy(y_mel[0].data.cpu().numpy()),
              "slice/mel_gen": utils.plot_spectrogram_to_numpy(y_hat_mel[0].data.cpu().numpy()), 
              "all/mel": utils.plot_spectrogram_to_numpy(mel[0].data.cpu().numpy()),
              "all/attn": utils.plot_alignment_to_numpy(attn[0,0].data.cpu().numpy())
          }
          utils.summarize(
            writer=writer,
            global_step=global_step, 
            images=image_dict,
            scalars=scalar_dict)

        if global_step % hps.train.eval_interval == 0:
          evaluate(hps, net_g, eval_loader, writer_eval)
          utils.save_checkpoint(net_g, optim_g, hps.train.learning_rate, epoch, os.path.join(hps.model_dir, "G_fine_tuning{}.pth".format(global_step)))
          #utils.save_checkpoint(net_d, optim_d, hps.train.learning_rate, epoch, os.path.join(hps.model_dir, "D_{}.pth".format(global_step)))
      global_step += 1
  
  if rank == 0:
    logger.info('====> Epoch: {}'.format(epoch))

 
def evaluate(hps, generator, eval_loader, writer_eval, mode = 'pre-training'):
    generator.eval()
    with torch.no_grad():
      if mode == 'pre-training':
        for batch_idx, (x, x_lengths, spec, spec_lengths, y, y_lengths) in enumerate(eval_loader):
          x, x_lengths = x.cuda(0), x_lengths.cuda(0)
          spec, spec_lengths = spec.cuda(0), spec_lengths.cuda(0)
          y, y_lengths = y.cuda(0), y_lengths.cuda(0)

          # remove else
          x = x[:1]
          x_lengths = x_lengths[:1]
          spec = spec[:1]
          spec_lengths = spec_lengths[:1]
          y = y[:1]
          y_lengths = y_lengths[:1]
          break
        y_hat, attn, mask, *_ = generator.module.infer_pre_training(y, y_lengths, max_len=1000)
        y_hat_lengths = mask.sum([1,2]).long() * hps.data.hop_length

      mel = spec_to_mel_torch(
        spec, 
        hps.data.filter_length, 
        hps.data.n_mel_channels, 
        hps.data.sampling_rate,
        hps.data.mel_fmin, 
        hps.data.mel_fmax)
      y_hat_mel = mel_spectrogram_torch(
        y_hat.squeeze(1).float(),
        hps.data.filter_length,
        hps.data.n_mel_channels,
        hps.data.sampling_rate,
        hps.data.hop_length,
        hps.data.win_length,
        hps.data.mel_fmin,
        hps.data.mel_fmax
      )
    image_dict = {
      "gen/mel": utils.plot_spectrogram_to_numpy(y_hat_mel[0].cpu().numpy())
    }
    audio_dict = {
      "gen/audio": y_hat[0,:,:y_hat_lengths[0]]
    }
    if global_step == 0:
      image_dict.update({"gt/mel": utils.plot_spectrogram_to_numpy(mel[0].cpu().numpy())})
      audio_dict.update({"gt/audio": y[0,:,:y_lengths[0]]})

    utils.summarize(
      writer=writer_eval,
      global_step=global_step, 
      images=image_dict,
      audios=audio_dict,
      audio_sampling_rate=hps.data.sampling_rate
    )
    generator.train()

                           
if __name__ == "__main__":
  main()
