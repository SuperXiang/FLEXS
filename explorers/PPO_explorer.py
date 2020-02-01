import collections
import tensorflow as tf
from functools import partial
from tf_agents.agents.ppo import ppo_policy, ppo_agent, ppo_utils
from tf_agents.drivers import dynamic_episode_driver
from tf_agents.environments import tf_py_environment
from tf_agents.environments.utils import validate_py_environment
from tf_agents.metrics import tf_metrics
from tf_agents.networks import actor_distribution_network
from tf_agents.networks import value_network
from tf_agents.replay_buffers import tf_uniform_replay_buffer

from environments.PPO_environment import PPOEnvironment as PPOEnv
from explorers.base_explorer import Base_explorer
from utils.sequence_utils import translate_one_hot_to_string

class PPO_explorer(Base_explorer):
    def __init__(self,
                 batch_size=100,
                 alphabet="UCGA",
                 virtual_screen=10,
                 path="./simulations/",
                 debug=False):
        super().__init__(batch_size,
                           alphabet,
                           virtual_screen,
                           path,
                           debug)
    
        self.explorer_type = "PPO_Agent"
        
        self.meas_seqs = []
        self.meas_seqs_it = 0
        
        self.top_seqs = collections.deque(maxlen=self.batch_size)
        self.top_seqs_it = 0
        
        self.has_pretrained_agent = False
        
    def initialize_env(self):
        env = PPOEnv(alphabet=self.alphabet,
                     starting_seq=self.meas_seqs[0][1],
                     landscape=self.model,
                     max_num_steps=self.virtual_screen)

        validate_py_environment(env, episodes=1)

        self.tf_env = tf_py_environment.TFPyEnvironment(env)
        
    def initialize_agent(self):
        actor_fc_layers = (200, 100)
        value_fc_layers = (200, 100)
        
        actor_net = actor_distribution_network.ActorDistributionNetwork(
            self.tf_env.observation_spec(),
            self.tf_env.action_spec(),
            fc_layer_params=actor_fc_layers)
        value_net = value_network.ValueNetwork(
            self.tf_env.observation_spec(), fc_layer_params=value_fc_layers)
        
        num_epochs = 10
        agent = ppo_agent.PPOAgent(
            self.tf_env.time_step_spec(),
            self.tf_env.action_spec(),
            optimizer=tf.compat.v1.train.AdamOptimizer(learning_rate=1e-5),
            actor_net=actor_net,
            value_net=value_net,
            num_epochs=num_epochs,
            summarize_grads_and_vars=False
        )
        agent.initialize()
        
        self.agent = agent
    
    def add_last_seq_in_trajectory(self, experience, new_seqs):
        """
        Given a trajectory object, checks if
        the object is the last in the trajectory,
        then adds the sequence corresponding
        to the state to batch.

        If the episode is ending, it changes the
        "current sequence" of the environment
        to the next one in `last_batch`,
        so that when the environment resets, mutants
        are generated from that new sequence.
        """
        
        if experience.is_boundary():
            seq = translate_one_hot_to_string(
                experience.observation.numpy()[0], self.alphabet)
            new_seqs.add(seq)
            
            self.meas_seqs_it = (self.meas_seqs_it + 1) % len(self.meas_seqs)
            self.tf_env.pyenv.envs[0].seq = self.meas_seqs[self.meas_seqs_it][1]
    
    def pretrain_agent(self):
        measured_seqs = [(self.model.get_fitness(seq),
                          seq, self.model.cost)
                          for seq in self.model.measured_sequences]
        measured_seqs = sorted(measured_seqs,
                               key=lambda x: x[0],
                               reverse=True)

        self.top_seqs = collections.deque(measured_seqs, maxlen=self.batch_size)
        self.meas_seqs = measured_seqs
        
        self.initialize_env()
        self.initialize_agent()
        
        batch_size = self.batch_size
        max_env_steps = 50*self.batch_size
        
        all_seqs = set(self.model.measured_sequences)
        proposed_seqs = set()
        measured_seqs = []
        
        num_parallel_environments = 1
        env_steps_metric = tf_metrics.EnvironmentSteps()
        step_metrics = [
            tf_metrics.NumberOfEpisodes(),
            env_steps_metric
        ]
        
        replay_buffer_capacity = 10001
        replay_buffer = tf_uniform_replay_buffer.TFUniformReplayBuffer(
            self.agent.collect_data_spec,
            batch_size=num_parallel_environments,
            max_length=replay_buffer_capacity
        )
        
        collect_driver = dynamic_episode_driver.DynamicEpisodeDriver(
            self.tf_env,
            self.agent.collect_policy,
            observers=[replay_buffer.add_batch,
                       partial(self.add_last_seq_in_trajectory,
                               new_seqs=proposed_seqs)] + step_metrics,
            num_episodes=1
        )
        while env_steps_metric.result() < max_env_steps:
            print(f"Episodes: {env_steps_metric.result().numpy()}/{max_env_steps}")

            # generate new sequences
            for _ in range(batch_size):
                collect_driver.run()

            # get proposed sequences which have not already been measured
            # (since the landscape is not updating)
            new_seqs = proposed_seqs.difference(all_seqs)
            
            # add new sequences to measured_sequences and sort
            self.meas_seqs += [(self.model.get_fitness(seq),
                               seq, self.model.cost)
                               for seq in new_seqs]
            self.meas_seqs = sorted(self.meas_seqs,
                                   key=lambda x: x[0],
                                   reverse=True)

            print(f"Number of measured sequences: {len(self.meas_seqs)}")
            # if we have a new winner
            if len(self.top_seqs) == 0 or self.meas_seqs[0][0] > self.top_seqs[-1][0]:
                print("New top sequence:", self.meas_seqs[0])
                self.top_seqs.append(self.meas_seqs[0])

            # add proposed sequences to set of all sequences
            all_seqs.update(proposed_seqs)
            
            # reset counter
            self.meas_seqs_it = 0

            # reset proposed sequences
            proposed_seqs.clear()

            # train from the agent's trajectories
            trajectories = replay_buffer.gather_all()
            total_loss, _ = self.agent.train(experience=trajectories)
            replay_buffer.clear()
            
        self.has_pretrained_agent = True
    
    def propose_samples(self):
        if not self.has_pretrained_agent:
            self.pretrain_agent()
            
        all_seqs = set(self.model.measured_sequences)
        new_seqs = set()
        last_batch = self.get_last_batch()
        
        num_parallel_environments = 1
        
        replay_buffer_capacity = 10001
        replay_buffer = tf_uniform_replay_buffer.TFUniformReplayBuffer(
            self.agent.collect_data_spec,
            batch_size=num_parallel_environments,
            max_length=replay_buffer_capacity
        )
            
        collect_driver = dynamic_episode_driver.DynamicEpisodeDriver(
            self.tf_env,
            self.agent.collect_policy,
            observers = [replay_buffer.add_batch,
                         partial(self.add_last_seq_in_trajectory,
                                 new_seqs=new_seqs)],
            num_episodes = 1
        )
        
        # reset counter?
        
        while len(new_seqs.difference(all_seqs)) < self.batch_size:
            collect_driver.run()
            
        new_seqs = new_seqs.difference(all_seqs)
        
        # add new sequences to measured_sequences and sort
        self.meas_seqs += [(self.model.get_fitness(seq),
                           seq, self.model.cost)
                           for seq in new_seqs]
        self.meas_seqs = sorted(self.meas_seqs,
                               key=lambda x: x[0],
                               reverse=True)
            
        trajectories = replay_buffer.gather_all()
        total_loss, _ = self.agent.train(experience=trajectories)
        replay_buffer.clear()
            
        return new_seqs