import utils, torch, time, os, pickle, imageio, math
from scipy.misc import imsave
import numpy as np
import torch.nn as nn
import torch.optim as optim
from torch.autograd import Variable, grad
from torch.utils.data import DataLoader
from torchvision import datasets, transforms
import pdb
from utils import Flatten
import matplotlib.pyplot as plt

#BatchNorm -> LayerNorm or pixelnorma

class Generator(nn.Module):
    def __init__(self):
        super(Generator, self).__init__()
        self.input_dim = 300
        self.input_height = 1
        self.input_width = 1
        self.output_dim = 3


        # Upsample + conv2d is better than convtranspose2d
        self.deconv = nn.Sequential(
            # 4
            nn.Conv2d(self.input_dim, 512, 4, 1, 3, bias=False),
            nn.InstanceNorm2d(512, affine=True),
            nn.LeakyReLU(0.2),

            # 8
            nn.Upsample(scale_factor=2, mode='nearest'),
            nn.Conv2d(512, 256, 3, 1, 1, bias=False),
            nn.InstanceNorm2d(256, affine=True),
            nn.LeakyReLU(0.2),
            
            nn.Conv2d(256, 256, 3, 1, 1, bias=False),
            nn.InstanceNorm2d(256, affine=True),
            nn.LeakyReLU(0.2),

            # 16
            nn.Upsample(scale_factor=2, mode='nearest'),
            nn.Conv2d(256, 128, 3, 1, 1, bias=False),
            nn.InstanceNorm2d(128, affine=True),
            nn.LeakyReLU(0.2),

            nn.Conv2d(128, 128, 3, 1, 1, bias=False),
            nn.InstanceNorm2d(128, affine=True),
            nn.LeakyReLU(0.2),

            # 32
            nn.Upsample(scale_factor=2, mode='nearest'),
            nn.Conv2d(128, 64, 3, 1, 1, bias=False),
            nn.InstanceNorm2d(64, affine=True),
            nn.LeakyReLU(0.2),

            nn.Conv2d(64, 64, 3, 1, 1, bias=False),
            nn.InstanceNorm2d(64, affine=True),
            nn.LeakyReLU(0.2),

            # 64
            nn.Upsample(scale_factor=2, mode='nearest'),
            nn.Conv2d(64, self.output_dim, 3, 1, 1, bias=False),
            nn.Sigmoid(),
        )


    def forward(self, feature):
        feature = feature.view(-1, self.input_dim, 1, 1)
        x = self.deconv(feature)
        return x

class Discriminator(nn.Module):
    def __init__(self, num_cls):
        super(Discriminator, self).__init__()
        self.input_dim = 3
        self.num_cls = num_cls

        self.conv = nn.Sequential(
            nn.Conv2d(self.input_dim, 32, 4, 2, 1, bias=False), # 64 -> 32
            nn.InstanceNorm2d(32, affine=True),
            nn.LeakyReLU(0.2),

            nn.Conv2d(32, 64, 3, 1, 1, bias=False),  # 32 -> 16
            nn.InstanceNorm2d(64, affine=True),
            nn.LeakyReLU(0.2),
            nn.Conv2d(64, 64, 3, 1, 1, bias=False),
            nn.InstanceNorm2d(64, affine=True),
            nn.LeakyReLU(0.2),
            nn.AvgPool2d(kernel_size=2),


            nn.Conv2d(64, 128, 3, 1, 1, bias=False),  # 16 -> 8
            nn.InstanceNorm2d(128, affine=True),
            nn.LeakyReLU(0.2),
            nn.Conv2d(128, 128, 3, 1, 1, bias=False),
            nn.InstanceNorm2d(128, affine=True),
            nn.LeakyReLU(0.2),
            nn.AvgPool2d(kernel_size=2),

            nn.Conv2d(128, 256, 3, 1, 1, bias=False),  # 8 -> 4
            nn.InstanceNorm2d(256, affine=True),
            nn.LeakyReLU(0.2),
            nn.Conv2d(256, 256, 3, 1, 1, bias=False),
            nn.InstanceNorm2d(256, affine=True),
            nn.LeakyReLU(0.2),
            nn.AvgPool2d(kernel_size=2),
        )

        self.convCls = nn.Sequential(
            nn.Conv2d(256, self.num_cls, 4, bias=False),
        )

        self.convGAN = nn.Sequential(
            nn.Conv2d(256, 1, 4, bias=False),
            nn.Sigmoid(),
            #Flatten()
        )

    def forward(self, y_):
        feature = self.conv(y_)

        fGAN = self.convGAN(feature).squeeze(3).squeeze(2)
        fcls = self.convCls(feature).squeeze(3).squeeze(2)

        return fGAN, fcls

class denseGAN(object):
    def __init__(self, args):
        #parameters
        self.batch_size = 128 #args.batch_size
        self.epoch = 300#args.epoch
        
        self.save_dir = '../models'#args.save_dir
        self.result_dir = '../results'#args.result_dir
        self.dataset = "ImageNet"#args.dataset
        self.dataroot_dir = '../../ImageNet/ILSVRC/Data/DET'#args.dataroot_dir
        '''
        self.log_dir = args.log_dir
        self.multi_gpu = args.multi_gpu
        '''
        self.model_name = args.gan_type+args.comment
        self.sample_num = 128
        self.gpu_mode = True#args.gpu_mode
        self.num_workers = 0#args.num_workers
        self.beta1 = args.beta1
        self.beta2 = args.beta2
        self.lrG = args.lrG
        self.lrD = args.lrD
        self.type = "train"
        self.lambda_ = 0.25
        self.n_critic = args.n_critic

        self.enc_dim = 300
        self.num_cls = 10


        #load dataset
        self.data_loader = DataLoader(utils.ImageNet(root_dir = '../../ImageNet/ILSVRC/Data/DET',transform=transforms.Compose([transforms.Scale(100), transforms.RandomCrop(64),  transforms.ToTensor()]),_type=self.type),
                                      batch_size=self.batch_size, shuffle=True, num_workers=self.num_workers)
        
        #self.num_cls = self.data_loader.dataset.num_cls # number of class ImageNet

        #networks init
        self.G = Generator()
        self.D = Discriminator(num_cls=self.num_cls)

        self.G_optimizer = optim.Adam(self.G.parameters(), lr=self.lrG, betas=(self.beta1, self.beta2))
        self.D_optimizer = optim.Adam(self.D.parameters(), lr=self.lrD, betas=(self.beta1, self.beta2))

        if self.gpu_mode:
            self.G = self.G.cuda()
            self.D = self.D.cuda()
            self.CE_loss = nn.CrossEntropyLoss().cuda()
            self.BCE_loss = nn.BCELoss().cuda()
            self.MSE_loss = nn.MSELoss().cuda()
            self.L1_loss = nn.L1Loss().cuda()
            self.ML_loss = nn.MultiLabelMarginLoss().cuda()
            self.sample_z_ = Variable(torch.rand((self.batch_size, self.enc_dim)).cuda(), volatile=True)
        else:
            self.CE_loss = nn.CrossEntropyLoss()
            self.BCE_loss = nn.BCELoss()
            self.MSE_loss = nn.MSELoss()
            self.L1_loss = nn.L1Loss()
            self.ML_loss = nn.MultiLabelMarginLoss()
            self.sample_z_ = Variable(torch.rand((self.batch_size, self.enc_dim)), volatile=True)

    def train(self):
        self.train_hist = {}
        self.train_hist['D_loss'] = []
        self.train_hist['G_loss'] = []
        self.train_hist['per_epoch_time'] = []
        self.train_hist['total_time'] = []

        if self.gpu_mode:
            self.y_real_, self.y_fake_ = Variable(torch.ones(self.batch_size, 1).cuda()), Variable(torch.zeros(self.batch_size, 1).cuda())
        else:
            self.y_real_, self.y_fake_ = Variable(torch.ones(self.batch_size, 1)), Variable(torch.zeros(self.batch_size, 1))


        #train
        self.D.train()
        start_time = time.time()
        for epoch in range(self.epoch):
            self.G.train()
            epoch_start_time = time.time()
            for iB, (x_, class_label) in enumerate(self.data_loader):
                
                if iB == self.data_loader.dataset.__len__() // self.batch_size:
                    break

                #--Make Laten Space--#
                z_ = torch.rand(self.batch_size, self.enc_dim)
                #z_ = torch.FloatTensor(self.batch_size, self.enc_dim).normal_(0.0, 1.0)


                if self.gpu_mode:
                    x_, z_, class_label_ = Variable(x_.cuda()), Variable(z_.cuda()), Variable(class_label.cuda())
                else:
                    x_, z_, class_label_ = Variable(x_), Variable(z_), Variable(class_label)



                #----Update D_network----#
                
                self.D_optimizer.zero_grad()
                D_real, C_real = self.D(x_)
                D_real_loss = self.BCE_loss(D_real, self.y_real_)
                #C_real_loss = self.CE_loss(C_real, class_label_)

                G_ = self.G(z_)
                D_fake, C_fake = self.D(G_)
                D_fake_loss = self.BCE_loss(D_fake, self.y_fake_)
                #C_fake_loss = self.CE_loss(C_fake, class_label_)

                # gradient penalty
                if self.gpu_mode:
                    alpha = torch.rand(x_.size()).cuda()
                else:
                    alpha = torch.rand(x_.size())

                x_hat = Variable(alpha * x_.data + (1 - alpha) * G_.data, requires_grad=True)

                pred_hat, class_hat = self.D(x_hat)
                if self.gpu_mode:
                    gradients = grad(outputs=pred_hat, inputs=x_hat, grad_outputs=torch.ones(pred_hat.size()).cuda(),
                                 create_graph=True, retain_graph=True, only_inputs=True)[0]
                else:
                    gradients = grad(outputs=pred_hat, inputs=x_hat, grad_outputs=torch.ones(pred_hat.size()),
                                     create_graph=True, retain_graph=True, only_inputs=True)[0]

                gradient_penalty = self.lambda_ * ((gradients.view(gradients.size()[0], -1).norm(2, 1) - 1) ** 2).mean()




                D_loss = D_real_loss + D_fake_loss + gradient_penalty
                self.train_hist['D_loss'].append(D_loss.data[0])
                
                num_correct_real = torch.sum(D_real > 0.5)
                num_correct_fake = torch.sum(D_fake < 0.5)

                D_acc = float(num_correct_real.data[0] + num_correct_fake.data[0]) / (self.batch_size * 2)


                D_loss.backward()
                if D_acc<0.8:
                    #print("D train!")
                    self.D_optimizer.step()
               



                #----Update G Network----#
                for iG in range(self.n_critic):
                    self.G_optimizer.zero_grad()
                
                    G_ = self.G(z_)
                    D_fake, C_fake= self.D(G_)

                    G_fake_loss = self.BCE_loss(D_fake, self.y_real_)
                    #C_fake_loss = self.CE_loss(C_fake, class_label_)
                    #G_recon_loss = self.MSE_loss(G_, y_)
                    #G_recon_loss = self.L1_loss(G_, y_)

                    num_wrong_fake = torch.sum(D_fake > 0.5)
                    G_acc = float(num_wrong_fake.data[0]) / self.batch_size

                    G_loss = G_fake_loss #+C_fake_loss
                    if iG == 0:
                        print("[E%03d]"%epoch,"G_loss : ", G_loss.data[0], "  D_loss : ", D_loss.data[0], "   D_acc : ", D_acc, "  G_acc : ", G_acc)
                        self.train_hist['G_loss'].append(G_loss.data[0])
                
                    G_loss.backward()
                    self.G_optimizer.step()


                #if (((iB+1)%100)) == 0:
                    #print('[E%03d]'%(epoch+1), 'G_loss : ', G_loss.data[0], '  D_loss : ' , D_loss.data[0],  '  D_acc : ' , D_acc, '  G_acc : ', G_acc)
                    
                    

            #---- Check train result ----#
            self.train_hist['per_epoch_time'].append(time.time()-epoch_start_time)
            self.visualize_results((epoch+1))
            utils.loss_plot(self.train_hist, os.path.join(self.result_dir, self.dataset, self.model_name), self.model_name)
            #We can check with or without Encoder output at here ex) self.G.Dec(z_) vs self.G(x_,z_)
                    
        self.train_hist['total_time'].append(time.time() - start_time)
        print("Avg one epoch time: %.2f, total %d epochs time: %.2f" % (np.mean(self.train_hist['per_epoch_time']),
              self.epoch, self.train_hist['total_time'][0]))
        print("Training finish!... save training results")

        self.save()

    def visualize_results(self, epoch, fix=True):
        self.G.eval()
        if not os.path.exists(self.result_dir + '/' + self.dataset + '/' + self.model_name):
            os.makedirs(self.result_dir + '/' + self.dataset + '/' + self.model_name)
		
        tot_num_samples = min(self.sample_num, self.batch_size)
        image_frame_dim = int(np.floor(np.sqrt(tot_num_samples)))

        if fix:
            """ fixed noise """
            samples = self.G(self.sample_z_)
        else:
            """ random noise """
            if self.gpu_mode:
                sample_z_ = Variable(torch.rand((self.batch_size, self.enc_dim)).cuda(), volatile=True)
            else:
                sample_z_ = Variable(torch.rand((self.batch_size, self.enc_dim)), volatile=True)
            samples = self.G(sample_z_)

        if self.gpu_mode:
            samples = samples.cpu().data.numpy().transpose(0, 2, 3, 1)
        else:
            samples = samples.numpy().data.transpose(0, 2, 3, 1)

        utils.save_images(samples[:image_frame_dim*image_frame_dim,:,:,:], [image_frame_dim, image_frame_dim], self.result_dir+'/'+self.dataset+'/'+self.model_name+'/'+self.model_name+'_epoch%03d'%epoch+'.png')


    def save(self):
        save_dir = os.path.join(self.save_dir, self.dataset, self.model_name)

        if not os.path.exists(save_dir):
            os.makedirs(save_dir)

        torch.save(self.G.state_dict(), os.path.join(save_dir, self.model_name + '_G.pkl'))
        torch.save(self.D.state_dict(), os.path.join(save_dir, self.model_name + '_D.pkl'))

        with open(os.path.join(save_dir, self.model_name + '_history.pkl'), 'wb') as f:
            pickle.dump(self.train_hist, f)

    def load(self):
        save_dir = os.path.join(self.save_dir, self.dataset, self.model_name)

        self.G.load_state_dict(torch.load(os.path.join(save_dir, self.model_name + '_G.pkl')))
        self.D.load_state_dict(torch.load(os.path.join(save_dir, self.model_name + '_D.pkl')))


