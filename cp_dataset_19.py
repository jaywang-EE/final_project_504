#coding=utf-8
import torch
import torch.utils.data as data
import torchvision.transforms as transforms
from numpy.random import randint

from PIL import Image
from PIL import ImageDraw

import os.path as osp
import numpy as np
import json

class CPDataset(data.Dataset):
    """Dataset for CP-VTON.
    """
    def __init__(self, opt):
        super(CPDataset, self).__init__()
        # base setting
        self.opt = opt
        self.root = opt.dataroot
        self.datamode = opt.datamode # train or test or self-defined
        self.stage = opt.stage # GMM or TOM
        self.data_list = opt.data_list
        self.fine_height = opt.fine_height
        self.fine_width = opt.fine_width
        self.radius = opt.radius
        self.data_path = osp.join(opt.dataroot, opt.datamode)
        self.transform = transforms.Compose([  \
                transforms.ToTensor(),   \
                # change
                transforms.Normalize((0.5,), (0.5,))])
                #transforms.Normalize((0.5, 0.5, 0.5), (0.5, 0.5, 0.5))])
        
        # load data list
        im_names = []
        c_names = []
        with open(osp.join(opt.dataroot, opt.data_list), 'r') as f:
            for line in f.readlines():
                im_name, c_name = line.strip().split()
                im_names.append(im_name)
                c_names.append(c_name)
        
        self.im_names = im_names
        self.c_names = c_names
        
    def name(self):
        return "CPDataset"

    def __getitem__(self, index):
        #c_index = randint(len(self.im_names))
        c_name = self.c_names[index]
        im_name = self.im_names[index]

        # cloth image & cloth mask
        wm = ""
        cm = ""
        if self.stage == 'HPM':
            c = Image.open(osp.join(self.data_path, 'cloth', c_name))
            #cm = Image.open(osp.join(self.data_path, 'cloth-mask', c_name))
        elif self.stage == "GMM":
            c = Image.open(osp.join(self.data_path, 'cloth', c_name))
            """
            wm = Image.open(osp.join(self.data_path, 'warp-mask', c_name))
            wm_array = np.array(wm)
            wm_array = (wm_array >= 128).astype(np.float32)
            wm = torch.from_numpy(wm_array)
            wm.unsqueeze_(0)
            """
        elif self.stage == "TOM":
            c = Image.open(osp.join(self.data_path, 'warp-cloth', c_name))
        else:
            print("Illegal type!")

        c = self.transform(c)  # [-1,1]

        if cm:
            cm_array = np.array(cm)
            cm_array = (cm_array >= 128).astype(np.float32)
            cm = torch.from_numpy(cm_array) # [0,1]
            cm.unsqueeze_(0)

        # person image 
        im = Image.open(osp.join(self.data_path, 'image', im_name))
        im = self.transform(im) # [-1,1]

        # load parsing image
        parse_name = im_name.replace('.jpg', '.png')
        if self.stage == 'HPM':
            im_parse = Image.open(osp.join(self.data_path, 'image-parse', parse_name))
        else:
            im_parse = Image.open(osp.join(self.data_path, 'image-seg', parse_name))

        #np.array(Image.open("test.png"))
        # parsing segmentation
        parse_array = np.array(im_parse)
        parse_arrays = [np.expand_dims((parse_array == i).astype(np.float32), axis=0) for i in range(16)]
        parse_shape = (parse_array > 0).astype(np.float32)
        parse_head = np.squeeze(parse_arrays[1] + parse_arrays[2] + parse_arrays[4] + parse_arrays[13])
        parse_cloth = np.squeeze(parse_arrays[5] + parse_arrays[6] + parse_arrays[7])
        parse_hands = np.squeeze(parse_arrays[14] + parse_arrays[15])
        parse_pants = np.squeeze(parse_arrays[9])

        parse_tensor_enc = torch.from_numpy(np.concatenate(parse_arrays,0))
        # for NLLloss
        parse_tensor = torch.from_numpy(parse_array).long()
        parse_tensor[parse_tensor>15] = 0
       
        # shape downsample
        parse_shape = Image.fromarray((parse_shape*255).astype(np.uint8))
        parse_shape = parse_shape.resize((self.fine_width//16, self.fine_height//16), Image.BILINEAR)
        parse_shape = parse_shape.resize((self.fine_width, self.fine_height), Image.BILINEAR)
        shape = self.transform(parse_shape) # [-1,1]

        pcm = torch.from_numpy(parse_cloth) # [0,1]
        phead = torch.from_numpy(parse_head) # [0,1]
        phand = torch.from_numpy(parse_hands) # [0,1]
        ppant = torch.from_numpy(parse_pants) # [0,1]

        # upper cloth
        print(parse_arrays.shape, parse_cloth.shape, pcm.shape)
        im_c = im * pcm + (1 - pcm) # [-1,1], fill 1 for other parts
        im_h = im * phead - (1 - phead) # [-1,1], fill 0 for other parts

        hand = im * phead - (1 - phead)
        pant = im * phead - (1 - phead)


        # load pose points
        pose_name = im_name.replace('.jpg', '_keypoints.json')
        with open(osp.join(self.data_path, 'pose', pose_name), 'r') as f:
            pose_label = json.load(f)
            pose_data = pose_label['people'][0]['pose_keypoints']
            pose_data = np.array(pose_data)
            pose_data = pose_data.reshape((-1,3))

        point_num = pose_data.shape[0]
        pose_map = torch.zeros(point_num, self.fine_height, self.fine_width)
        r = self.radius
        im_pose = Image.new('L', (self.fine_width, self.fine_height))
        pose_draw = ImageDraw.Draw(im_pose)
        for i in range(point_num):
            one_map = Image.new('L', (self.fine_width, self.fine_height))
            draw = ImageDraw.Draw(one_map)
            pointx = pose_data[i,0]
            pointy = pose_data[i,1]
            if pointx > 1 and pointy > 1:
                draw.rectangle((pointx-r, pointy-r, pointx+r, pointy+r), 'white', 'white')
                pose_draw.rectangle((pointx-r, pointy-r, pointx+r, pointy+r), 'white', 'white')
            one_map = self.transform(one_map)
            pose_map[i] = one_map[0]

        # just for visualization
        im_pose = self.transform(im_pose)
        
        # cloth-agnostic representation
        if self.stage == 'HPM':
            agnostic = torch.cat([im_h, shape, pose_map], 0) 
        elif self.stage == 'GMM':
            agnostic = "NO"
        elif self.stage == 'TOM':
            #print(im_h.dtype, pose_map.dtype, parse_tensor.float().dtype, hand.dtype, pant.dtype)
            agnostic = torch.cat([im_h, pose_map, parse_tensor.unsqueeze(0).float(), hand, pant], 0) 

        if self.stage == 'GMM':
            im_g = Image.open('grid.png')
            im_g = self.transform(im_g)
        else:
            im_g = ''

        result = {
            'c_name':   c_name,     # for visualization
            'im_name':  im_name,    # for visualization or ground truth
            'cloth':    c,          # for input
            'cloth_mask':     cm,   # for input
            'warped_mask': pcm,
            'hand': hand,
            'pant': pant,
            'image':    im,         # for visualization
            'agnostic': agnostic,   # for input
            'parse_cloth': im_c,    # for ground truth
            'seg': parse_tensor,    # for ground truth
            'seg_enc': parse_tensor_enc,    # for ground truth
            'shape': shape,         # for visualization
            'pose_image': im_pose,  # for visualization
            'grid_image': im_g,     # for visualization
        }

        return result

    def __len__(self):
        return len(self.im_names)

class CPDataLoader(object):
    def __init__(self, opt, dataset):
        super(CPDataLoader, self).__init__()

        if opt.shuffle :
            train_sampler = torch.utils.data.sampler.RandomSampler(dataset)
        else:
            train_sampler = None

        self.data_loader = torch.utils.data.DataLoader(
                dataset, batch_size=opt.batch_size, shuffle=(train_sampler is None),
                num_workers=opt.workers, pin_memory=True, sampler=train_sampler, drop_last=True)
        self.dataset = dataset
        self.data_iter = self.data_loader.__iter__()
       
    def next_batch(self):
        try:
            batch = self.data_iter.__next__()
        except StopIteration:
            self.data_iter = self.data_loader.__iter__()
            batch = self.data_iter.__next__()

        return batch


if __name__ == "__main__":
    print("Check the dataset for geometric matching module!")
    
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataroot", default = "data")
    parser.add_argument("--datamode", default = "train")
    parser.add_argument("--stage", default = "GMM")
    parser.add_argument("--data_list", default = "train_pairs.txt")
    parser.add_argument("--fine_width", type=int, default = 192)
    parser.add_argument("--fine_height", type=int, default = 256)
    parser.add_argument("--radius", type=int, default = 3)
    parser.add_argument("--shuffle", action='store_true', help='shuffle input data')
    parser.add_argument('-b', '--batch-size', type=int, default=4)
    parser.add_argument('-j', '--workers', type=int, default=1)
    
    opt = parser.parse_args()
    dataset = CPDataset(opt)
    data_loader = CPDataLoader(opt, dataset)

    print('Size of the dataset: %05d, dataloader: %04d' \
            % (len(dataset), len(data_loader.data_loader)))
    first_item = dataset.__getitem__(0)
    first_batch = data_loader.next_batch()

    from IPython import embed; embed()

