import os.path as osp
import random

random.seed(326)

with open("data/train_pairs.txt", 'r') as f:
    im_names = []
    c_names = []

    for line in f.readlines():
        im_name, c_name = line.strip().split()
        im_names.append(im_name)
        c_names.append(c_name)

    random.shuffle(c_names)
    print(c_names[:20])

    reformated_names = ""
    for im_name, c_name in zip(im_names, c_names):
        reformated_names += (im_name + " " + c_name + "\n")
    
    with open('data/train_pairs_new.txt', 'w') as fw:
        fw.write(reformated_names)
