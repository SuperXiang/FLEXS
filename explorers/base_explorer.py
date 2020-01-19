from meta.explorer import Explorer
import os.path
from utils.sequence_utils import generate_random_mutant


class Base_explorer(Explorer):

    def __init__(self, batch_size = 100, alphabet ="UCGA" , virtual_screen = 10, path = "./simulations/", debug= False):
        self.alphabet = alphabet
        self.batch_size = batch_size
        self.virtual_screen = virtual_screen
        self.batches = {-1:""}
        self.explorer_type ="Base"
        self.horizon = 1
        self.path = path
        self.debug = debug
    
    @property
    def file_to_write(self):
        return  f'{self.path}{self.explorer_type}.csv'

    def write(self,round, overwrite):
        if not os.path.exists(self.file_to_write) or (round==0 and overwrite):
            with open(self.file_to_write,"w") as output_file:
                output_file.write("""batch,sequence,true_score,model_score,batch_size,measurement_cost,virtual_evals,landscape_id,start_id,model_type, virtual_screen,horizon,explorer_type\n""")

        with open(self.file_to_write,"a") as output_file:
                batch = self.get_last_batch()
                for sequence in self.batches[batch]:
                        output_file.write(f'{batch},{sequence},{self.batches[batch][sequence][1]},{self.batches[batch][sequence][0]},{self.batch_size},{self.model.cost},{self.model.evals},{self.model.landscape_id},{self.model.start_id},{self.model.model_type},{self.virtual_screen}, {self.horizon},{self.explorer_type}\n')


    def get_last_batch(self):
        return max(self.batches.keys())


    def set_model(self,model, reset = True):
        if reset:
            self.batches={-1:""}     
        self.model = model
        if self.model.cost > 0:
            batch = self.get_last_batch()+1
            self.batches[batch]={}
            for seq in self.model.measured_sequences:
                score = self.model.get_fitness(seq)
                self.batches[batch][seq]=[score,score]

    def propose_samples(self):
        '''implement this function for your own explorer'''
        raise NotImplementedError("propose_samples must be implemented by your explorer")
    

    def measure_proposals(self, proposals):
        to_measure = list(proposals)[:self.batch_size]
        last_batch=self.get_last_batch()
        self.batches[last_batch+1]={}
        for seq in to_measure:
            self.batches[last_batch+1][seq]=[self.model.get_fitness(seq)]
        self.model.update_model(to_measure)
        for seq in to_measure:
            self.batches[last_batch+1][seq].append(self.model.get_fitness(seq))
   

    def run(self,rounds, overwrite=False, verbose=True):
        self.horizon = rounds
        for r in range(rounds):
            if verbose:
               print (f'round: {r}, cost: {self.model.cost}, evals: {self.model.evals}, top: {max(self.model.measured_sequences.values())}') 
            new_samples = self.propose_samples()
            self.measure_proposals(new_samples)
            if not self.debug:
                self.write(r, overwrite)
            self.horizon-=1



class Random_explorer(Base_explorer):

    def __init__(self,mu, batch_size = 100, alphabet ="UCGA" , virtual_screen = 10,  path = "./simulations/" , debug=False):
        super(Random_explorer, self).__init__(batch_size, alphabet, virtual_screen, path, debug )
        self.mu = mu
        self.explorer_type =f'Random_mu{self.mu}'

    def propose_samples(self):
        new_seqs=set()
        last_batch=self.get_last_batch()
        while len(new_seqs) < self.batch_size:
            for seq in self.batches[last_batch]:
                new_seq = generate_random_mutant(seq, self.mu, alphabet = self.alphabet) 
                if new_seq not in self.model.measured_sequences:
                    new_seqs.add(new_seq)
        return new_seqs







  