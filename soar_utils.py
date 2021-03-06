#!/usr/bin/env python3

from abc import abstractmethod
from argparse import ArgumentParser
from ast import literal_eval
from contextlib import contextmanager
from copy import deepcopy
from imp import load_module
from inspect import Parameter, signature
from itertools import chain, product
from os.path import exists, join
from types import GeneratorType
import re
import sys

# dynamically find the Soar trunk
PYTHON_SML_FILE = "Python_sml_ClientInterface.py"
python_sml_files = [join(p, PYTHON_SML_FILE) for p in sys.path if exists(join(p, "Python_sml_ClientInterface.py"))]
if python_sml_files:
    python_sml = python_sml_files[0]
    with open(python_sml) as fd:
        load_module("Python_sml_ClientInterface", fd, python_sml, ('.py', 'U', 1))
else:
    print("Cannot find Python_sml_ClientInterface.py in " + ":".join(sys.path))
    exit(1)

import Python_sml_ClientInterface as sml

# SML wrappers

class Agent:
    class Identifier:
        def __init__(self, agent, wme):
            assert isinstance(wme, sml.Identifier)
            self.agent = agent
            self.wme = wme
        def __eq__(self, other):
            return isinstance(other, Agent.Identifier) and hash(self) == hash(other)
        def __hash__(self):
            return self.time_tag
        @property
        def time_tag(self):
            return self.wme.GetTimeTag()
        def children(self):
            for index in range(self.wme.GetNumberChildren()):
                yield self.agent._get_wme(self.wme.GetChild(index))
        def add_child(self, attribute, value):
            self.agent.create_wme(self, attribute, value)
    class WME:
        def __init__(self, agent, wme):
            assert isinstance(wme, sml.WMElement)
            self.agent = agent
            self.wme = wme
        @property
        def identifier(self):
            return self.agent._get_identifier(self.wme.ConvertToIdentifier())
        @property
        def attribute(self):
            return str(self.wme.GetAttribute())
        @property
        def value_type(self):
            value_type = self.wme.GetValueType()
            if value_type == "int":
                return int
            elif value_type == "float":
                return float
            elif value_type == "string":
                value = self.wme.ConvertToStringElement().GetValue()
                if value in ("true", "false"):
                    return bool
                else:
                    return str
            else:
                return Agent.Identifier
        @property
        def value(self):
            if self.value_type == bool:
                return False if str(self.wme.ConvertToStringElement().GetValue()) == "false" else True
            elif self.value_type == int:
                return int(self.wme.ConvertToIntElement().GetValue())
            elif self.value_type == float:
                return float(self.wme.ConvertToFloatElement().GetValue())
            elif self.value_type == str:
                return str(self.wme.ConvertToStringElement().GetValue())
            else:
                return self.agent._get_identifier(self.wme.ConvertToIdentifier())
    def __init__(self, agent):
        self.agent = agent
        self.identifiers = {}
    @property
    def name(self):
        return str(self.agent.GetAgentName())
    @property
    def input_link(self):
        return self._get_identifier(self.agent.GetInputLink())
    @property
    def output_link(self):
        # this can be None if the agent has not put anything on the output link ever
        ol = self.agent.GetOutputLink()
        if ol:
            return self._get_identifier(ol)
        else:
            return None
    def _get_identifier(self, identifier):
        assert isinstance(identifier, sml.Identifier)
        if identifier.GetTimeTag() not in self.identifiers:
            self.identifiers[identifier.GetTimeTag()] = Agent.Identifier(self, identifier)
        return self.identifiers[identifier.GetTimeTag()]
    def _get_wme(self, wme):
        assert isinstance(wme, sml.WMElement)
        return Agent.WME(self, wme)
    def create_wme(self, identifier, attribute, value):
        assert isinstance(identifier, Agent.Identifier)
        assert isinstance(attribute, str)
        if isinstance(value, bool):
            return self._get_wme(self.agent.CreateStringWME(identifier.wme, attribute, ("true" if value else "false")))
        if isinstance(value, int):
            return self._get_wme(self.agent.CreateIntWME(identifier.wme, attribute, value))
        elif isinstance(value, float):
            return self._get_wme(self.agent.CreateFloatWME(identifier.wme, attribute, value))
        elif isinstance(value, str):
            return self._get_wme(self.agent.CreateStringWME(identifier.wme, attribute, value))
        elif isinstance(value, Agent.Identifier):
            return self._get_wme(self.agent.CreateSharedIdWME(identifier.wme, attribute, value))
        elif value is None:
            return self._get_wme(self.agent.CreateIdWME(identifier.wme, attribute))
        else:
            raise TypeError()
    def destroy_wme(self, wme):
        assert isinstance(wme, Agent.WME)
        return bool(self.agent.DestroyWME(wme.wme))
    def execute_command_line(self, command):
        return str(self.agent.ExecuteCommandLine(command))
    def register_for_run_event(self, event, function, user_data):
        return int(self.agent.RegisterForRunEvent(event, function, user_data))
    def unregister_for_run_event(self, event_id):
        return bool(self.agent.UnregisterForRunEvent(event_id))
    def register_for_print_event(self, event, function, user_data):
        return int(self.agent.RegisterForPrintEvent(event, function, user_data))
    def unregister_for_print_event(self, event_id):
        return bool(self.agent.UnregisterForPrintEvent(event_id))

class Kernel:
    def __init__(self, kernel):
        self.kernel = kernel
    def create_agent(self, name):
        agent = self.kernel.CreateAgent(name)
        if agent is None:
            raise RuntimeError("Error creating agent: " + self.kernel.GetLastErrorDescription())
        return Agent(agent)
    def destroy_agent(self, agent):
        assert isinstance(agent, Agent)
        return self.kernel.DestroyAgent(agent.agent)
    def shutdown(self):
        return self.kernel.Shutdown()

def create_kernel_in_current_thread():
    kernel = sml.Kernel.CreateKernelInCurrentThread()
    if kernel is None or kernel.HadError():
        raise RuntimeError("Error creating kernel: " + kernel.GetLastErrorDescription())
    return Kernel(kernel)

@contextmanager
def create_agent():
    kernel = create_kernel_in_current_thread()
    agent = kernel.create_agent("test")
    try:
        yield agent
    finally:
        kernel.destroy_agent(agent)
        kernel.shutdown()
        del kernel

# mid-level framework

def cli(agent):
    agent.register_for_print_event(sml.smlEVENT_PRINT, callback_print_message, None)
    command = input("soar> ")
    while command not in ("exit", "quit"):
        if command:
            print(agent.execute_command_line(command).strip())
        command = input("soar> ")

def str_to_parameters(s):
    parameters = {}
    for pair in s.split():
        k, v = pair.split("=")
        try:
            v = literal_eval(v)
        except SyntaxError:
            pass
        parameters[k] = v
    return parameters

def parameterize_commands(parameters, commands):
    return [cmd.format(**parameters) for cmd in commands]

def run_parameterized_commands(agent, parameters, commands):
    for cmd in parameterize_commands(parameters, commands):
        agent.execute_command_line(cmd)

# environment template and example

# FIXME would like to allow agent to send data back for the report

class SoarEnvironment:
    class Command:
        def __init__(self, wme):
            assert isinstance(wme, Agent.WME)
            self.wme = wme
            self.name = self.wme.attribute
            self.arguments = {}
            for parameter in self.wme.value.children():
                self.arguments[parameter.attribute] = parameter.value
        def add_status(self, status):
            self.wme.value.add_child("status", status)
    def __init__(self, agent):
        self.agent = agent
        self.wmes = {}
        self.processed_commands = set()
        self.io_initialized = False
        self.output_event_id = self.agent.register_for_run_event(sml.smlEVENT_AFTER_OUTPUT_PHASE, SoarEnvironment.update, self)
    @abstractmethod
    def initialize_io(self):
        raise NotImplementedError()
    @abstractmethod
    def update_io(self):
        raise NotImplementedError()
    def del_wme(self, parent, attr, child):
        if (parent not in self.wmes) or (attr not in self.wmes[parent]) or (child not in self.wmes[parent][attr]):
            return False
        self.agent.destroy_wme(self.wmes[parent][attr][child])
        del self.wmes[parent][attr][child]
        if len(self.wmes[parent][attr]) == 0:
            del self.wmes[parent][attr]
        if len(self.wmes[parent]) == 0:
            del self.wmes[parent]
        return True
    def add_wme(self, parent, attr, child=None):
        if parent not in self.wmes:
            self.wmes[parent] = {}
        if attr not in self.wmes[parent]:
            self.wmes[parent][attr] = {}
        new_wme = None
        if child is None:
            self.wmes[parent][attr][child] = set()
            new_wme = self.agent.create_wme(parent, attr, child)
            self.wmes[parent][attr][child].add(new_wme)
        else:
            new_wme = self.agent.create_wme(parent, attr, child)
            self.wmes[parent][attr][child] = new_wme
        return new_wme
    def parse_output_commands(self):
        commands = set()
        output_link = self.agent.output_link
        if output_link is not None:
            for command_wme in output_link.children():
                if command_wme.identifier.time_tag not in self.processed_commands:
                    commands.add(SoarEnvironment.Command(command_wme))
                    self.processed_commands.add(command_wme.identifier.time_tag)
        return commands
    @staticmethod
    def update(mid, user_data, agent, message):
        if not user_data.io_initialized:
            user_data.initialize_io()
            user_data.io_initialized = True
        user_data.update_io()
        agent.Commit()

class Ticker(SoarEnvironment):
    def __init__(self, agent):
        super().__init__(agent)
        self.time = 0
    def initialize_io(self):
        self.add_wme(self.agent.input_link, "time", self.time)
    def update_io(self):
        commands = self.parse_output_commands()
        for command in commands:
            if command.name == "print" and "message" in command.arguments:
                print(command.arguments["message"])
                command.add_status("complete")
            else:
                command.add_status("error")
        self.del_wme(self.agent.input_link, "time", self.time)
        self.time += 1
        self.add_wme(self.agent.input_link, "time", self.time)

# experiment template and example

class ParameterSpace:
    def __init__(self, **parameters):
        self.parameter_space = NameSpace(**parameters)
        self.filters = set()
        self.dependent_functions = {}
        self._repair_parameter_space()
    def _repair_parameter_space(self):
        non_list_keys = (k for k, v in self.parameter_space.items() if not isinstance(v, tuple))
        for k in non_list_keys:
            if any(isinstance(self.parameter_space[k], t) for t in (list, range, GeneratorType)):
                self.parameter_space[k] = tuple(self.parameter_space[k])
            else:
                self.parameter_space[k] = (self.parameter_space[k],)
    def clone(self):
        return deepcopy(self)
    @property
    def size(self):
        return len(list(self.permutations()))
    @property
    def parameters(self):
        return tuple(self.parameter_space.keys())
    @property
    def variable_parameters(self):
        return tuple(k for k, v in self.parameter_space.items() if len(v) > 1)
    @property
    def dependent_parameters(self):
        return tuple(self.dependent_functions.keys())
    @property
    def constant_parameters(self):
        return tuple(k for k, v in self.parameter_space.items() if len(v) == 1)
    def get_parameter_values(self, parameter):
        return self.parameter_space[parameter]
    def add_filter(self, fn):
        self.filters.add(fn)
    def add_dependent_parameter(self, name, fn):
        self.dependent_functions[name] = fn
    def factorize_parameters(self, **defaults):
        self.add_filter((lambda p: sum((1 if key in p and p[key] != value else 0) for key, value in defaults.items()) <= 1))
    def add_if_then_filter(self, antecedent, consequent):
        self.add_filter((lambda p: (not antecedent(p) or consequent(p))))
    def fix_parameters(self, **parameters):
        self.parameter_space.update(**parameters)
        self._repair_parameter_space()
    def permutations(self):
        keys = sorted(self.parameter_space.keys())
        for values in product(*(self.parameter_space[key] for key in keys)):
            parameters = NameSpace(**dict(zip(keys, values)))
            for name, fn in self.dependent_functions.items():
                parameters[name] = fn(parameters)
            if all(fn(parameters) for fn in self.filters):
                yield parameters

class SoarExperiment:
    class ParameterizedSoarEnvironment(SoarEnvironment):
        def __init__(self, agent, environment_class, parameters):
            super().__init__(agent)
            self.environment_class = environment_class
            self.parameters = parameters
            self.environment_instance = environment_class(agent, *self.linearize_parameters())
            self.agent.unregister_for_run_event(self.environment_instance.output_event_id)
        def linearize_parameters(self):
            return tuple(self.parameters[key] for key, parameter in positional_arguments(self.environment_class.__init__) if key != "agent")
        def initialize_io(self):
            params_wme = self.add_wme(self.agent.input_link, "parameters")
            for key in self.parameters.keys():
                self.add_wme(params_wme.identifier, key.replace("_", "-"), self.parameters[key])
            self.environment_instance.initialize_io()
        def update_io(self):
            self.environment_instance.update_io()
    def __init__(self, environment_class, commands, reporters, parameter_space=None):
        self.environment_class = environment_class
        self.commands = commands
        self.reporters = reporters
        if parameter_space is not None:
            self.set_parameter_space(parameter_space)
        else:
            self.parameter_space = parameter_space
        self.prerun_procedures = set()
    def set_parameter_space(self, parameter_space):
        self.parameter_space = parameter_space
    def register_prerun_procedure(self, f):
        self.prerun_procedures.add(f)
    def run_all(self, repl=False):
        self.run_with(repl=repl)
    def run_with(self, repl=False, **updates):
        parameter_space = self.parameter_space.clone()
        parameter_space.fix_parameters(**updates)
        report_ordering = sorted(parameter_space.variable_parameters) + sorted(parameter_space.dependent_parameters) + sorted(parameter_space.constant_parameters) + sorted(self.reporters.keys()) # FIXME hack
        for parameters in parameter_space.permutations():
            missing_arguments = set(dict(positional_arguments(self.environment_class)).keys()) - set(parameters.__dict__.keys())
            assert len(missing_arguments) == 1, "missing arguments: {}".format(" ".join(sorted(missing_arguments)))
            self.run(parameters, report_ordering, repl=repl)
    def run(self, parameters, report_ordering, repl=False):
        report = {}
        report.update(parameters)
        with create_agent() as agent:
            environment = SoarExperiment.ParameterizedSoarEnvironment(agent, self.environment_class, parameters)
            for f in self.prerun_procedures:
                f(environment.environment_instance, parameters, agent)
            if repl:
                for command in parameterize_commands(parameters, self.commands):
                    print("soar> " + command.strip())
                    print(agent.execute_command_line(command).strip())
                agent.execute_command_line("watch 1")
                cli(agent)
            else:
                for command in parameterize_commands(parameters, self.commands):
                    agent.execute_command_line(command)
                agent.execute_command_line("run")
            for name, reporter in self.reporters.items():
                report[name] = reporter(environment.environment_instance, parameters, agent)
        print(to_literal_str(report))
    def cli(self):
        arg_parser = ArgumentParser()
        arg_parser.add_argument("--repl", action="store_true", default=False, help="start an interactive command line")
        for key in sorted(self.parameter_space.parameters):
            arg_parser.add_argument("--" + key.replace("_", "-"))
        args = arg_parser.parse_args()
        parameters = {}
        for key, value in args.__dict__.items():
            if value is not None:
                parameters[key] = intellicast(value)
        self.run_with(**parameters)

class ExperimentsCLI:
    def __init__(self, experiment, default_parameter_space, experiment_parameter_spaces):
        self.experiment = experiment
        self.default_parameter_space = default_parameter_space
        self.experiment_parameter_spaces = experiment_parameter_spaces
    def cli(self):
        arg_parser = ArgumentParser()
        arg_parser.add_argument("experiment", nargs="*", default=[None], metavar="EXPERIMENT", help="experiment to run")
        arg_parser.add_argument("--repl", action="store_true", default=False, help="start an interactive command line")
        arg_parser.add_argument("--print-parameter-space", action="store_true", default=False, help="print size of parameter space")
        for key in sorted(self.default_parameter_space.parameters):
            arg_parser.add_argument("--" + key.replace("_", "-"))
        args = arg_parser.parse_args()
        if any(experiment is not None and experiment not in self.experiment_parameter_spaces.keys() for experiment in args.experiment):
            arg_parser.error("EXPERIMENT must be one of:\n{}".format("\n".join("\t{}".format(experiment) for experiment in self.experiment_parameter_spaces.keys())))
        arguments = dict((k, intellicast(v)) for k, v in args.__dict__.items() if k not in ("experiment", "print_parameter_space") and v is not None)
        if args.print_parameter_space:
            for experiment in args.experiment:
                if experiment is None:
                    pspace = self.default_parameter_space.clone()
                    pspace.fix_parameters(**arguments)
                    print("\n".join(" ".join("{}={}".format(k, v) for k, v in sorted(space.items()) if k in chain(pspace.variable_parameters, pspace.dependent_parameters)) for space in pspace.permutations()))
                else:
                    for experiment in args.experiment:
                        pspace = self.experiment_parameter_spaces[experiment].clone()
                        pspace.fix_parameters(**arguments)
                        print("\n".join(" ".join("{}={}".format(k, v) for k, v in sorted(space.items()) if k in chain(pspace.variable_parameters, pspace.dependent_parameters)) for space in pspace.permutations()))
        else:
            for experiment in args.experiment:
                if experiment is None:
                    self.experiment.set_parameter_space(self.default_parameter_space)
                else:
                    self.experiment.set_parameter_space(self.experiment_parameter_spaces[experiment])
                self.experiment.run_with(**arguments)

# callback functions

def callback_print_message(mid, user_data, agent, message):
    print(message.strip())

def print_report_row(mid, user_data, agent, *args):
    condition = user_data["condition"]
    param_map = user_data["param_map"]
    domain = user_data["domain"]
    reporters = user_data["reporters"]
    if condition(param_map, domain, agent):
        pairs = []
        pairs.extend("=".join([k, str(v)]) for k, v in param_map.items())
        pairs.extend("{}={}".format(*reporter(param_map, domain, agent)) for reporter in reporters)
        print(" ".join(pairs))

def report_data_wrapper(param_map, domain, reporters, condition=None):
    if condition is None:
        condition = (lambda param_map, domain, agent: True)
    return {
        "condition": condition,
        "param_map": param_map,
        "domain": domain,
        "reporters": reporters,
    }

# common reporters

def num_decisions(environment, parameters, agent):
    return float(re.sub("^.*\n([0-9]+) decisions.*", r"\1", agent.execute_command_line("stats"), flags=re.DOTALL))

def avg_decision_time(environment, parameters, agent):
    return float(re.sub(r".*\(([0-9.]+) msec/decision.*", r"\1", agent.execute_command_line("stats"), flags=re.DOTALL))

def max_decision_time(environment, parameters, agent):
    result = re.sub(r".*  Time \(sec\) *([0-9.]+).*", r"\1", agent.execute_command_line("stats -M"), flags=re.DOTALL)
    return float(result) * 1000

def kernel_cpu_time(environment, parameters, agent):
    result = re.sub(".*Kernel CPU Time: *([0-9.]+).*", r"\1", agent.execute_command_line("stats"), flags=re.DOTALL)
    return float(result) * 1000

# utilities

class NameSpace:
    def __init__(self, **kwargs):
        self.update(**kwargs)
    def __eq__(self, other):
        if not isinstance(other, NameSpace):
            return False
        return vars(self) == vars(other)
    def __str__(self):
        return "NameSpace(" + ", ".join("{}={}".format(k, v) for k, v in sorted(self.items())) + ")"
    def __contains__(self, key):
        return key in self.__dict__
    def __getitem__(self, key):
        if key in self.__dict__:
            return self.__dict__[key]
        raise KeyError(key)
    def __setitem__(self, key, value):
        setattr(self, key, value)
    def __delitem__(self, key):
        if key in self.__dict__:
            delattr(self, key)
        raise KeyError(key)
    def __iter__(self):
        return self.__dict__.keys()
    def update(self, **kwargs):
        for key, value in kwargs.items():
            self[key] = value
    def keys(self):
        return self.__dict__.keys()
    def values(self):
        return self.__dict__.values()
    def items(self):
        return self.__dict__.items()

def to_literal_str(obj):
    if obj is None:
        return "None"
    elif type(obj) in (int, float):
        return str(obj)
    if type(obj) == str:
        return '"{}"'.format(obj.replace('"', '\\"'))
    elif type(obj) == list:
        return "[{}]".format(", ".join(to_literal_str(o) for o in obj))
    elif type(obj) == dict:
        return "{{{}}}".format(", ".join("{}:{}".format(to_literal_str(key), to_literal_str(value)) for key, value in obj.items()))
    elif type(obj) == set:
        return "{{{}}}".format(", ".join(to_literal_str(e) for e in obj))
    elif hasattr(obj, "__iter__"):
        return "({})".format(", ".join(to_literal_str(o) for o in obj))
    else:
        raise ValueError("Unknown type {}".format(type(obj)))

def intellicast(string):
    try:
        return int(string)
    except ValueError:
        pass
    try:
        return float(string)
    except ValueError:
        pass
    try:
        return literal_eval(string)
    except ValueError:
        pass
    return string

def positional_arguments(fn):
    return tuple((name, parameter) for name, parameter in signature(fn).parameters.items() if name != "self" and parameter.default == Parameter.empty)

def main():
    with create_agent() as agent:
        print(agent.execute_command_line("""
            sp {propose*init-agent
                (state <s> ^superstate nil
                          -^name)
            -->
                (<s> ^operator.name init-agent)
            }
            sp {apply*init-agent
                (state <s> ^operator.name init-agent)
            -->
                (<s> ^name ticker)
            }
            sp {ticker*propose*print
                (state <s> ^name ticker
                           ^io.input-link.time <time>)
            -->
                (<s> ^operator.name print)
            }
            sp {ticker*apply*print
                (state <s> ^name ticker
                           ^operator.name print
                           ^io <io>)
                (<io> ^input-link.time <time>
                      ^output-link <ol>)
            -->
                (<ol> ^print.message <time>)
            }
            sp {ticker*apply*all*remove-completed
                (state <s> ^operator.name
                           ^io.output-link <ol>)
                (<ol> ^<command> <cmd>)
                (<cmd> ^status complete)
            -->
                (<ol> ^<command> <cmd> -)
            }
            sp {ticker*fail
                (state <s> ^io.input-link <il>)
                (<il> ^time <t1>
                      ^time {<t2> <> <t1>})
            -->
                (write (crlf) |FAIL| (crlf))
                (halt)
            }
        """))
        Ticker(agent)
        cli(agent)

if __name__ == "__main__":
    main()
