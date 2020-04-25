#coding=utf-8
import torch
import torch.nn as nn
import torch.nn.functional as F
from torch.autograd import Variable

import argparse
import os
import time
from cp_dataset_19 import CPDataset, CPDataLoader
from networks import GMM, UnetGenerator, VGGLoss, load_checkpoint, save_checkpoint, load_checkpoints, save_checkpoints, Discriminator_G

from tensorboardX import SummaryWriter
from visualization import board_add_image, board_add_images, save_images, sm_image, combine_images

from datetime import datetime
import random

os.environ['CUDA_LAUNCH_BLOCKING'] = '1'

'''
HPM = Human Parsing Module
GMM = GMM
TOM = Try On Module
'''
'''
def random_crop(reals, fakes, winsize):
    y, x = [random.randint(reals.size(i)//4, int(reals.size(i)*0.75)-winsize-1) for i in (2, 3)]
    return reals[:,:,y:y+winsize,x:x+winsize], fakes[:,:,y:y+winsize,x:x+winsize]
'''

def get_opt():
    parser = argparse.ArgumentParser()
    parser.add_argument('-s', "--stage", required=True)

    parser.add_argument("--name", default = datetime.now().strftime("%m%d_%H%M"))
    parser.add_argument("--gpu_ids", default = "")
    
    parser.add_argument('-m', '--mode', default = "train")

    parser.add_argument('-j', '--workers', type=int, default=4)
    parser.add_argument('-b', '--batch-size', type=int, default=4)
    parser.add_argument('-d', '--debug', type=str, default="debug")
    parser.add_argument('-w', '--winsize', type=int, default=48)
    parser.add_argument('-l', '--lambda', type=float, default=1.)
    
    parser.add_argument("--display_count", type=int, default = 200)
    parser.add_argument("--save_count", type=int, default = 1000)
    parser.add_argument('-c', '--checkpoint', type=str, default='', help='model checkpoint for initialization')
    
    parser.add_argument("--dataroot", default = "data")
    parser.add_argument("--datamode", default = "train")
    parser.add_argument("--result_dir", default = "output")
    parser.add_argument("--data_list", default = "train_pairs.txt")
    parser.add_argument("--shuffle", action='store_false', help='shuffle input data')

    # training 
    parser.add_argument("--alpha", type=float, default = 1.) # FOR HPM

    parser.add_argument("--fine_width", type=int, default = 192)
    parser.add_argument("--fine_height", type=int, default = 256)
    parser.add_argument("--radius", type=int, default = 5)
    parser.add_argument("--grid_size", type=int, default = 5)
    parser.add_argument('--lr', type=float, default=0.0001, help='initial learning rate for adam')
    parser.add_argument('--tensorboard_dir', type=str, default='tensorboard', help='save tensorboard infos')
    parser.add_argument('--checkpoint_dir', type=str, default='checkpoints', help='save checkpoint infos')
    parser.add_argument("--keep_step", type=int, default = 100000)
    parser.add_argument("--decay_step", type=int, default = 100000)

    #viz
    parser.add_argument("--vizseg", action='store_true', help='visualization')

    opt = parser.parse_args()
    return opt

def test_hpm(opt, test_loader, model):
    model.cuda()
    model.eval()

    base_name = os.path.basename(opt.checkpoint)
    save_dir = os.path.join(opt.result_dir, base_name, opt.mode)
    if not os.path.exists(save_dir):
        os.makedirs(save_dir)
    image_seg_dir = os.path.join(save_dir, 'image-seg')
    if not os.path.exists(image_seg_dir):
        os.makedirs(image_seg_dir)

    for step, inputs in enumerate(test_loader.data_loader):
        iter_start_time = time.time()
        
        im_names = inputs['im_name']
        agnostic = inputs['agnostic'].cuda()
        c = inputs['cloth'].cuda()

        seg_gt = inputs['seg'].cuda()

        segmentation = model(torch.cat([agnostic, c],1))
        values, indices = segmentation.max(1, keepdim=True)
        # print(indices.shape)
        # print(seg_gt.shape)
        for i, im_name in enumerate(im_names):
            if opt.vizseg:
                sm_image(indices[i, :, :, :].double()/20., im_name.replace('.jpg', '.png'), image_seg_dir+'viz') 
                sm_image(seg_gt[i, :, :].unsqueeze(0).double()/20., im_name.replace('.jpg', '.png'), image_seg_dir+'vizo') 
            sm_image(indices[i, :, :, :].double()/255., im_name.replace('.jpg', '.png'), image_seg_dir) 


def train_hpm(opt, train_loader, model, d_g, board):
    model.cuda()
    model.train()
    d_g.cuda()
    d_g.train()

    dis_label = Variable(torch.FloatTensor(opt.batch_size)).cuda()
    
    # criterion
    criterionMCE = nn.CrossEntropyLoss()#nn.BCEWithLogitsLoss()
    #criterionMSE = nn.MSELoss()
    criterionGAN = nn.BCELoss()
    
    # optimizer
    optimizerG = torch.optim.Adam(model.parameters(), lr=opt.lr, betas=(0.5, 0.999))
    schedulerG = torch.optim.lr_scheduler.LambdaLR(optimizerG, lr_lambda = lambda step: 1.0 -
            max(0, step - opt.keep_step) / float(opt.decay_step + 1))

    optimizerD = torch.optim.Adam(d_g.parameters(), lr=opt.lr, betas=(0.5, 0.999))
    schedulerD = torch.optim.lr_scheduler.LambdaLR(optimizerD, lr_lambda = lambda step: 1.0 -
            max(0, step - opt.keep_step) / float(opt.decay_step + 1))
    
    for step in range(opt.keep_step + opt.decay_step):
        iter_start_time = time.time()
        #prep
        inputs = train_loader.next_batch()
            
        im = inputs['image'].cuda()#sz=b*3*256*192
        seg_gt = inputs['seg'].cuda()
        seg_enc = inputs['seg_enc'].cuda()

        agnostic = inputs['agnostic'].cuda()
        c = inputs['cloth'].cuda()
        batch_size = im.size(0)

        optimizerD.zero_grad()
        #D_real
        dis_label.data.fill_(1.0-random.random()*0.1)
        dis_g_output = d_g(seg_enc)
        
        errDg_real = criterionGAN(dis_g_output, dis_label)
        errDg_real.backward()

        #generate image
        segmentation = model(torch.cat([agnostic, c],1))

        #D_fake
        dis_label.data.fill_(0.0+random.random()*0.1)

        dis_g_output = d_g(segmentation.detach())
        errDg_fake = criterionGAN(dis_g_output, dis_label)
        errDg_fake.backward()
        optimizerD.step()


        #model_train
        optimizerG.zero_grad()
        dis_label.data.fill_(1.0-random.random()*0.1)
        dis_g_output = d_g(segmentation)
        errG_fake = criterionGAN(dis_g_output, dis_label)
        loss_mce = criterionMCE(segmentation.view(batch_size, 16, -1), seg_gt.view(batch_size, -1))

        loss = errG_fake + loss_mce * opt.alpha
        loss.backward()
        optimizerG.step()
                    
        if (step+1) % opt.display_count == 0:
            t = time.time() - iter_start_time
            
            loss_dict = {"GAN":errG_fake.item(), "TOT":loss.item(), "MCE":loss_mce.item(), 
                         "DG":((errDg_fake+errDg_real)/2).item()}
            print('step: %d|time: %.3f'%(step+1, t), end="")
            
            for k, v in loss_dict.items():
                print('|%s: %.3f'%(k, v), end="")
                board.add_scalar(k, v, step+1)
            print()
            
        if (step+1) % opt.save_count == 0:
            """
            save_checkpoint(model, os.path.join(opt.checkpoint_dir, opt.stage +'_'+ opt.name, 'step_%06d.pth' % (step+1)))
            save_checkpoint(d_g, os.path.join(opt.checkpoint_dir, opt.stage +'_'+ opt.name, 'step_%06d_dg.pth' % (step+1)))
            """
            save_checkpoint(model, os.path.join(opt.checkpoint_dir, opt.stage +'_'+ opt.name, 'model.pth'))
            save_checkpoint(d_g, os.path.join(opt.checkpoint_dir, opt.stage +'_'+ opt.name, 'dg.pth'))

def test_gmm(opt, test_loader, model):
    model.cuda()
    model.eval()

    base_name = os.path.basename(opt.checkpoint)
    save_dir = os.path.join(opt.result_dir, base_name, opt.datamode)
    if not os.path.exists(save_dir):
        os.makedirs(save_dir)
    warp_cloth_dir = os.path.join(save_dir, 'warp-cloth')
    if not os.path.exists(warp_cloth_dir):
        os.makedirs(warp_cloth_dir)

    for step, inputs in enumerate(test_loader.data_loader):        
        # im = inputs['image'].cuda()
        # im_pose = inputs['pose_image'].cuda()
        # shape = inputs['shape'].cuda()
        # agnostic = inputs['agnostic'].cuda()
        # cm = inputs['cloth_mask'].cuda()
        # im_c =  inputs['parse_cloth'].cuda()
        # im_g = inputs['grid_image'].cuda()

        c_names = inputs['c_name']
        c = inputs['cloth'].cuda()
        wm = inputs['warped_mask'].cuda()
            
        wm = wm.unsqueeze(1)
        grid, theta = model(wm, c)
        warped_cloth = F.grid_sample(c, grid, padding_mode='border')

        for i, c_name in enumerate(c_names):
            sm_image(warped_cloth[i, :, :, :].double(), c_name, warp_cloth_dir) 


def train_gmm(opt, train_loader, model, board):
    model.cuda()
    model.train()

    # criterion
    criterionL1 = nn.L1Loss()
    
    # optimizer
    optimizer = torch.optim.Adam(model.parameters(), lr=opt.lr, betas=(0.5, 0.999))
    scheduler = torch.optim.lr_scheduler.LambdaLR(optimizer, lr_lambda = lambda step: 1.0 -
            max(0, step - opt.keep_step) / float(opt.decay_step + 1))
    #change
    #loss_sum = 0
    for step in range(opt.keep_step + opt.decay_step):
        iter_start_time = time.time()
        inputs = train_loader.next_batch()
            
        im = inputs['image'].cuda()
        c = inputs['cloth'].cuda()
        #cm = inputs['cloth_mask'].cuda()
        wm = inputs['warped_mask'].cuda()
        im_c =  inputs['parse_cloth'].cuda()
        #im_g = inputs['grid_image'].cuda()
            
        wm = wm.unsqueeze(1)

        grid, theta = model(wm, c)
        warped_cloth = F.grid_sample(c, grid, padding_mode='border')
        """
        warped_mask = F.grid_sample(cm, grid, padding_mode='zeros')
        warped_grid = F.grid_sample(im_g, grid, padding_mode='zeros')
        """
        loss = criterionL1(warped_cloth, im_c)
        optimizer.zero_grad()
        loss.backward()
        optimizer.step()
        
        #loss_sum += loss.item()   

        if (step+1) % opt.display_count == 0:
            board.add_scalar('metric', loss.item(), step+1)
            t = time.time() - iter_start_time
            print('step: %8d, time: %.3f, loss: %.4f'%(step+1, t, loss.item()), flush=True)

        if (step+1) % opt.save_count == 0:
            """
            save_checkpoint(model, os.path.join(opt.checkpoint_dir, opt.name, 'step_%06d.pth' % (step+1)))
            """
            save_checkpoint(model, os.path.join(opt.checkpoint_dir, opt.name, 'model.pth'))

def test_tom(opt, test_loader, model):
    model.cuda()
    model.eval()

    base_name = os.path.basename(opt.checkpoint)
    save_dir = os.path.join(opt.result_dir, base_name, opt.datamode)
    if not os.path.exists(save_dir):
        os.makedirs(save_dir)
    tryon_dir = os.path.join(save_dir, 'tryon')
    if not os.path.exists(tryon_dir):
        os.makedirs(tryon_dir)

    for step, inputs in enumerate(test_loader.data_loader):        
        im_names = inputs['im_name']   
        agnostic = inputs['agnostic'].cuda()
        c = inputs['cloth'].cuda()
        warped_masks = inputs['warped_mask'].cuda()

        
        p_tryon = model(torch.cat([agnostic, c],1))

        for i, im_name in enumerate(im_names):
            #print(c.shape, p_tryon.shape, warped_masks.shape)
            #p_tryon = p_tryon * (1 - warped_masks) + c * warped_masks
            sm_image(p_tryon[i, :, :, :] * (1 - warped_masks[i, :, :]) + c[i, :, :, :] * warped_masks[i, :, :], im_name, tryon_dir) 

        #sm_image(warped_cloth, c_names, tryon_dir) 

def train_tom(opt, train_loader, model, board):
    model.cuda()
    model.train()
    
    # criterion
    criterionL1 = nn.L1Loss()
    criterionVGG = VGGLoss()
    criterionMask = nn.L1Loss()
    
    # optimizer
    optimizer = torch.optim.Adam(model.parameters(), lr=opt.lr, betas=(0.5, 0.999))
    scheduler = torch.optim.lr_scheduler.LambdaLR(optimizer, lr_lambda = lambda step: 1.0 -
            max(0, step - opt.keep_step) / float(opt.decay_step + 1))
    
    for step in range(opt.keep_step + opt.decay_step):
        iter_start_time = time.time()
        inputs = train_loader.next_batch()
            
        im = inputs['image'].cuda()
        im_pose = inputs['pose_image']
        shape = inputs['shape']

        agnostic = inputs['agnostic'].cuda()
        c = inputs['cloth'].cuda()
        
        p_tryon = model(torch.cat([agnostic, c],1))

        loss_l1 = criterionL1(p_tryon, im)
        loss_vgg = criterionVGG(p_tryon, im)
        #loss_mask = criterionMask(m_composite, cm)
        loss = loss_l1 + loss_vgg# + loss_mask
        optimizer.zero_grad()
        loss.backward()
        optimizer.step()
            
        if (step+1) % opt.display_count == 0:
            board.add_scalar('metric', loss.item(), step+1)
            board.add_scalar('L1', loss_l1.item(), step+1)
            board.add_scalar('VGG', loss_vgg.item(), step+1)
            #board.add_scalar('MaskL1', loss_mask.item(), step+1)
            t = time.time() - iter_start_time
            print('step: %8d, time: %.3f, loss: %.4f, l1: %.4f, vgg: %.4f' 
                    % (step+1, t, loss.item(), loss_l1.item(), 
                    loss_vgg.item()), flush=True)

        if (step+1) % opt.save_count == 0:
            """
            save_checkpoint(model, os.path.join(opt.checkpoint_dir, opt.name, 'step_%06d.pth' % (step+1)))
            """
            save_checkpoint(model, os.path.join(opt.checkpoint_dir, opt.name, 'model.pth'))
            
def main():
    opt = get_opt()

    if opt.mode == 'test':
        opt.datamode  = "test"
        opt.data_list = "test_pairs.txt"
        opt.shuffle = False
    elif opt.mode == 'val':
        opt.shuffle = False
    elif opt.mode != 'train':
        print(opt.mode)

    print(opt)

    if opt.mode != 'train' and not opt.checkpoint:
        print("You need to have a checkpoint for: "+opt.mode)
        return None

    print("Start to train stage: %s, named: %s!" % (opt.stage, opt.name))
   
    # create dataset 
    train_dataset = CPDataset(opt)

    # create dataloader
    train_loader = CPDataLoader(opt, train_dataset)

    # visualization
    if not os.path.exists(opt.tensorboard_dir):
        os.makedirs(opt.tensorboard_dir)
    board = SummaryWriter(log_dir = os.path.join(opt.tensorboard_dir, opt.name))
    
    # create model & train & save the final checkpoint
    if opt.stage == 'HPM':
        model = UnetGenerator(25, 16, 6, ngf=64, norm_layer=nn.InstanceNorm2d, clsf=True)
        d_g= Discriminator_G(opt, 16)
        if not opt.checkpoint =='' and os.path.exists(opt.checkpoint):
            load_checkpoint(model, opt.checkpoint)
            load_checkpoint(d_g, opt.checkpoint[:-9] + "dg.pth")

        if opt.mode == "train":
            train_hpm(opt, train_loader, model, d_g, board)
        else:
            test_hpm(opt, train_loader, model)

        save_checkpoints(model, d_g, os.path.join(opt.checkpoint_dir, opt.stage +'_'+ opt.name+"_final", '%s.pth'))

    elif opt.stage == 'GMM':
        #seg_unet = UnetGenerator(25, 16, 6, ngf=64, norm_layer=nn.InstanceNorm2d, clsf=True)
        model = GMM(opt, 1)
        if not opt.checkpoint =='' and os.path.exists(opt.checkpoint):
            load_checkpoint(model, opt.checkpoint)
        
        if opt.mode == "train":
            train_gmm(opt, train_loader, model, board)
        else:
            test_gmm(opt, train_loader, model)
        
        save_checkpoint(model, os.path.join(opt.checkpoint_dir, opt.name, 'gmm_final.pth'))
    
    elif opt.stage == 'TOM':
        model = UnetGenerator(31, 3, 6, ngf=64, norm_layer=nn.InstanceNorm2d)
        if not opt.checkpoint =='' and os.path.exists(opt.checkpoint):
            load_checkpoint(model, opt.checkpoint)

        if opt.mode == "train":
            train_tom(opt, train_loader, model, board)
        else:
            test_tom(opt, train_loader, model)
        
        save_checkpoint(model, os.path.join(opt.checkpoint_dir, opt.name, 'tom_final.pth'))
    else:
        raise NotImplementedError('Model [%s] is not implemented' % opt.stage)
  
    print('Finished training %s, nameed: %s!' % (opt.stage, opt.name))

if __name__ == "__main__":
    main()

