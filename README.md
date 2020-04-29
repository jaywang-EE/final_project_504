# IB-VTON implementation (ICIP 2019)
Implementation of eecs504-19W final project, based on cp-VTON.

## Download dataset
```
python data_download.py
```

## HPM train
```
python train_19.py --stage HPM --save_count 5000
```

## HPM evaluation
```
python train_19.py --stage HPM --m [test/val] --checkpoint <path_to_module>/hpm_final.pth
```

## GMM train
```
python train_19.py --stage GMM --save_count 5000
```

## GMM evaluation
```
python train_19.py --stage GMM --m [test/val] --checkpoint <path_to_module>/gmm_final.pth
```

## TOM train
```
python train_19.py --stage TOM --save_count 5000
```

## TOM evaluation
```
python train_19.py --stage TOM --m [test/val] --checkpoint <path_to_module>/gmm_final.pth
```
