"""pyvty.py

Provides terminal connection to a network device.
Supports connection via ssh or telnet using consistent methods.
"""

from __future__ import absolute_import
from __future__ import division
from __future__ import print_function
from __future__ import unicode_literals

import datetime
import getpass      # handles silent password prompt
import inspect      # introspection so fuctions can know their name debug mode
import paramiko     # ssh library
import re           # regular expressions
import socket       # used to test open tcp ports
import sys          # used to print to std.err
import telnetlib    # telnet library
import time         # used for time.sleep
import traceback    # provides exception traceback data

version = '0.7.1'

"""
Usage:

class Session(host, port, username, password, protocol)

TO DO LIST:
send - "exit" hangs until timeout on ssh (generates EOFError eception on telnet.

change allow_configuration to diable config
change configure to use a list (or docstring)
config from file method
handle --More-- or banner type config, or "exit" (check if connected?)

"""

exceptions = (
            socket.timeout,
            socket.error,
            paramiko.BadHostKeyException,
            paramiko.AuthenticationException,
            paramiko.SSHException,
            UserWarning,
            )

debug_level = 0


def debug_display_info(debug=0, message=None):
    """Prints current time and current method if debug=1.
    Also prints stack introspection when debug=2.
    """
    called_from = inspect.stack()[1][3]
    if debug > 0:
        if message is None:
            print("\n=== epoch: {0} === method: {1} ===".format(
                time.time(), called_from), file=sys.stderr)
        else:
            print('[{0}] {1}'.format(called_from, message), file=sys.stderr)
    if debug > 1:
        for line in inspect.stack()[1:]:
            print(line, file=sys.stderr)


def dual_print(*args, **kwargs):
    '''Prints to screen and to file.
    Specify a file handle using 'file=filehandle'.
    '''
    if 'file' in kwargs:
        if kwargs['file'] is not None:
            print(*args, **kwargs)
            kwargs['file'].flush()
            del kwargs['file']
    print(*args, **kwargs)


def get_username(username=None):
    if username is None:
        local_user = getpass.getuser()
        print('Username [{0}]: '.format(local_user), file=sys.stderr, end='')
        try:
            username = raw_input()  # Python2
        except NameError:
            username = input()  # Python3
        if not username:
            username = local_user
    return username


def get_password(password=None):
    while not password:
        verify = False
        while password != verify:
            if verify:
                print('Passwords do not match. Try again', file=sys.stderr)
            password = getpass.getpass()
            verify = getpass.getpass('Retype password: ')
    return password


def iface_short_name(interface):
    iface_regex = re.compile(r'^[A-Z][a-z]|[0-9][[0-9\-\:\.\/]*$')
    return ''.join(iface_regex.findall(interface))


def tcp_is_open(ip, tcp_port):
    global debug_level
    debug_display_info(debug=debug_level)
    debug_display_info(debug=debug_level, message=(ip, str(tcp_port)))
    connection = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    remote_socket = (ip, int(tcp_port))
    try:
        connection.settimeout(1.5)
        connection.connect(remote_socket)
        connection.shutdown(2)
        debug_display_info(debug=debug_level, message='returns True')
        return True
    except:
        debug_display_info(debug=debug_level, message='returns False')
        return False


def timestamp():
    return str(datetime.datetime.fromtimestamp(time.time()))


def filestamp():
    return timestamp().split('.')[0].replace(' ', '_').replace(':', '.')


def validate_host(host):
    global debug_level
    debug_display_info(debug=debug_level)
    # ipaddress.ip_address(socket.gethostbyname('panther'))
    #ipaddress.ip_address('host')
    #print socket.gethostbyname('localhost') # result from hosts file
    #print socket.getaddrinfo('google.com', 80)
    return host


def validate_port(port):
    global debug_level
    debug_display_info(debug=debug_level)
    try:
        port = int(port)
    except TypeError:
        port = None
    except ValueError:
        raise TypeError('Value specified for port is not an integer.')
    if port is not None:
        if port < 1 or port > 65535:
            raise ValueError('port must be between 1 and 65535')
    return port


def validate_protocol(protocol):
    global debug_level
    debug_display_info(debug=debug_level)
    valid_protocols = ['ssh', 'telnet']
    if protocol is None:
        return None
    try:
        protocol = protocol.lower()
    except TypeError:
        raise TypeError('protocol must be one of these {0}.'
            .format(str(valid_protocols)))


def determine_protocol(host, protocol=None, port=None):
    global debug_level
    debug_display_info(debug=debug_level)
    port = validate_port(port)
    protocol = validate_protocol(protocol)
    if protocol is None:
        protocol = {22 : 'ssh', 23 : 'telnet'}.get(port)
    if port is None:
        port = {'ssh' : 22, 'telnet' : 23}.get(protocol)
    if port is None:
        if tcp_is_open(host, 22):
            port, protocol = (22, 'ssh')
        elif tcp_is_open(host, 23):
            port, protocol = (23, 'telnet')
    return (protocol, port)


class Terminal(object):
    """Provides common methods to access a terminal using multiple protocols.

    Provides common methods to child classes.
    Child classes will provide primitive methods for connection setup,
    send, read, and connection close, which are unique to each implementation.
    The methods provided here leverage primitive methods to provide
    compex, common methods.  The child classes will inherit this logic.
    """

    def __init__(self, host, port=None, protocol=None, **kwargs):
        global debug_level
        self.debug = kwargs.get('debug', 0)
        debug_level = self.debug
        debug_display_info(debug=self.debug)
        self.kwargs = kwargs
        self.platform = kwargs.get('platform', 'cisco')
        try:
            self.username = kwargs['username']
            self.password = kwargs['password']
        except KeyError as exception:
            print('Missing required argument: {0}'.format(exception), file=sys.stderr)
        self.host = host
        self.protocol, self.port = determine_protocol(host, protocol, port)
        self._set_defaults()
        self.connect()

    def __iter__(self):
        """Not really sure this class needs to be iterable.
        It was a good coding excercise, might have added some complexity 
        to the update buffer method in the fine-tuning delays 
        and trying to detect when no more buffer will be sent.
        """
        return self

    def __next__(self):
        # python3 method calls python2 method.
        # I did it this way because python2 method is 'public'
        return self.next()

    def _set_defaults(self):
        debug_display_info(debug=self.debug)
        self.terminal = None
        self.data_buffer = u''
        self.last_regex_match = u''
        self.banner = False
        self.prompt_matched = False
        self.timeout = 20
        self.prompt = r'[\r\n](\w[\w\-\:\.]+ ?(\(\w[\w\-\:\.]+\) ?)?[\>\$\#\%] ?)$'
        self.logfile = self.kwargs.get('logfile', None)
        self.last_regex_match = u''
        self.disable_paging = u'terminal length 0'
        self.send_delay = 0.1
        self.read_delay = 0.002
        self.read_retries = 50
        self.exceptions = (
            socket.timeout,
            socket.error,
            paramiko.BadHostKeyException,
            paramiko.AuthenticationException,
            paramiko.SSHException,
            UserWarning,
            )

    def connect(self, **kwargs):
        # check kwargs - is this called by user or class ??
        # self.terminal should be assigned to False in __init__
        debug_display_info(debug=self.debug)
        hostdict = {
            'port':self.port, 
            'username':self.username, 
            'password':self.password,
            }
        if self.terminal:
            return False
        if self.protocol is None:
            raise socket.error('Cannot connect to host via ssh or telnet.')
        if self.protocol == 'ssh':
            self.terminal = SSH(self.host, **hostdict)
        elif self.protocol == 'telnet':
            self.terminal = Telnet(self.host, **hostdict)
            self.login(self.username, self.password)
        if self.platform == 'cisco':
            self.enable_privilege()
            self.send(self.disable_paging)
        return True

    def close(self):
        if self.terminal:
            self.terminal._close()
            self.terminal = None

    def login(self, 
            username, 
            password, 
            enable_command="enable", 
            enable_password=None,
            ):
        """Login to terminal session and elevate privilege level.
        
        Requires username, password.
        """
        debug_display_info(debug=self.debug)
        debug_display_info(debug=self.debug, message=self.data_buffer)
        login_prompt = r'[Uu]sername|[Ll]ogin|[Nn]ame'
        password_prompt = r'[Pp]assword'
        auth_fail = r'Authentication failed'

        self.read_until_regex(r'|'.join((self.prompt, login_prompt)))
        debug_message = 'LAST MATCH = {0}'.format(self.last_regex_match)
        debug_display_info(debug=self.debug, message=debug_message)
        if re.search(self.prompt, self.last_regex_match):
            debug_message = 'LEAVING LOGIN -- ALREADY LOGGED IN!'
            debug_display_info(debug=self.debug, message=debug_message)
            return True
        self.write(username)
        self.read_until_regex(password_prompt)
        debug_message = 'LAST MATCH = {0}'.format(self.last_regex_match)
        debug_display_info(debug=self.debug, message=debug_message)
        self.write(password)
        self.read_until_regex(r'|'.join((self.prompt, login_prompt, auth_fail)))
        if re.search(r'|'.join((login_prompt, auth_fail)), self.last_regex_match):
            raise UserWarning('Authentication Failed')

    def next(self):
        """Returns one line at a time when object is called as an interable.

        Method returns the available output up until first newline encountered.
        If no newline exists, all remaining output is returned.
        """
        debug_display_info(debug=self.debug)
        time.sleep(self.read_delay)
        if not '\n' in self.data_buffer:
            self.update_buffer()
        if not self.data_buffer:
            raise StopIteration
        try:
            output, self.data_buffer = self.data_buffer.split('\n', 1)
        except ValueError:
            output, self.data_buffer = self.data_buffer, u''
        return output

    def enable_privilege(self, command="enable", password=None):
        """Elevate privilege level from read-only to read-write
        
        Also called 'enable mode'.
        By default, uses the same password that was used at login.
        Specify password='some_other_password' to override.
        Sends the command 'enable' by default.
        Use privilege_command='enable'
        """
        debug_display_info(debug=self.debug)
        if password is None:
            password = self.password
        prompt = r'^\w[\w\(\)]+ ?[\>\$\#] ?$|[Pp]assword:? ?$'
        #self.write('')
        #self.read_until_regex(prompt)
        self.write(command)
        self.read_until_regex(prompt)
        current_match = self.last_regex_match
        while re.search(r'[Pp]assword:? ?$', current_match):
            self.write(password)
            self.read_until_regex(prompt)
            current_match = self.last_regex_match
        if re.search(r'# ?$', current_match):
            return True
        return False

    def flush_buffer(self):
        """Discards all available terminal output."""
        debug_display_info(debug=self.debug)
        self.terminal._read()
        self.data_buffer = u''
        return True

    def update_buffer(self, retries=None):
        """Reads all avalable terminal output and appends to data_buffer."""
        debug_display_info(debug=self.debug)
        if retries is None:
            retries = self.read_retries
        result = False
        early_exit = re.compile(r'(?<![\>\$\#\%])([\>\$\#\%] ?$)')
        this_delay = self.read_delay
        max_delay = self.read_delay * retries
        while this_delay <= max_delay:
            received_data = self.terminal._read()
            if received_data:
                self.write_to_log(received_data, prefix='')
                result = True
                self.data_buffer += received_data
                this_delay = self.read_delay
                if early_exit.search(self.data_buffer):
                    # We may have found shell prompt: minimize max_delay.
                    max_delay = this_delay
                else:
                    # Ensure max delay is reset to original value.
                    max_delay = self.read_delay * retries
            else:
                # No data received: increment this_delay
                this_delay += self.read_delay
            time.sleep(self.read_delay)
        debug_display_info(debug=self.debug, message=self.data_buffer)
        return result

    def read(self):
        """Returns all available terminal output  as a string"""
        debug_display_info(debug=self.debug)
        self.update_buffer()
        output, self.data_buffer = self.data_buffer, u''
        return output

    def read_until(self, match, timeout=None):
        """This will match a pattern, return text before the first match."""
        if timeout is None:
            timeout = self.timeout
        debug_display_info(debug=self.debug)
        debug_display_info(debug=self.debug, message='match = {0}'.format(match))
        time.sleep(self.read_delay)
        end_time = time.time() + timeout
        while end_time > time.time():
            while self.update_buffer():
                end_time = time.time() + timeout
            if match in self.data_buffer:
                (output, post_match) = self.data_buffer.split(match, 1)
                self.data_buffer = match + post_match
                return output
            else:
                time.sleep(0.1)
        # Reached timeout at this point: should I raise an exception?
        output = self.data_buffer
        self.flush_buffer()
        return output

    def read_until_regex(self, match, timeout=None):
        """This will match a regular expression.
        
        Return everything before the first regex match.
        self.last_regex_match is assigned the string matching the regex.
        Timeout counter is reset whenever new data appears on terminal.
        If timeout occurs, self.last_regex_match will keep previous value.
        """
        ###  Should check if terminal closed, and then return the buffer.
        debug_display_info(debug=self.debug)
        debug_display_info(debug=self.debug, message='match = {0}'.format(match))
        if timeout is None:
            timeout = self.timeout
        time.sleep(self.read_delay)
        end_time = time.time() + timeout
        regex = re.compile(match, re.MULTILINE)
        while end_time > time.time():
            while self.update_buffer():
                end_time = time.time() + timeout
            regex_match = regex.search(self.data_buffer)
            if regex_match:
                self.prompt_matched = True
                self.last_regex_match = regex_match.group()
                split_up = regex.split(self.data_buffer, 1)
                (output, post_match) = split_up[0], split_up[-1]
                self.data_buffer = self.last_regex_match + post_match
                return output
            else:
                time.sleep(0.1)
        # Reached timeout at this point: should I raise an exception?
        # Should I overwrite self.last_regex_match? 
        self.prompt_matched = False
        debug_message = '%%% Timed out after {0} seconds.'.format(timeout)
        debug_display_info(debug=self.debug, message=debug_message)
        output = self.data_buffer
        self.flush_buffer()
        return output

    def write(self, text, end='\n', send=True):
        """Sends string to terminal with trailing newline.
        
        To prevent trailing newline, include end='' as a keywork argument.
        """
        if not send:
            return '[SEND=FALSE] {0}'.format(command)
        debug_display_info(debug=self.debug)
        debug_display_info(debug=self.debug, message='WRITE: {0}'.format(text))
        result = self.terminal._write(text + end)
        time.sleep(self.send_delay)
        return result

    def _send_main(self, command, prompt, timeout, end):
        """Sends a command to the terminal and waits for the prompt to return."""
        # FIX ME : should return immediately upon exception:
        #       send---exception: Socket is closed
        #   HMMM - should just raise the exception
        #       rather then return an error meesage
        #       leaving the script to handle the exception
        #    I don't think I can make it 'wrappable' via 'with' context manager
        debug_display_info(debug=self.debug)
        
        # Banner Checking
        if command.lstrip().startswith('banner'):
            if len(command.lstrip().split()) > 2:
                self.banner = command.lstrip().split()[2][0]
            else:
                self.banner = command.lstrip().split()[-1][0]
            debug_message = 'banner delimeter = {0}'.format(self.banner)
            debug_display_info(debug=self.debug, message=debug_message)
            if len(command.lstrip().split()) > 3:
                if self.banner == command.lstrip().split()[-1][-1]:
                    self.banner = False
                    debug_message = 'banner delimeter found in banner statement.'
                    debug_display_info(debug=self.debug, message=debug_message)
        # Banner Checking
        if self.banner:        
            timeout = 0.2
            debug_message = 'banner timeout set to {0} seconds.'.format(timeout)
            debug_display_info(debug=self.debug, message=debug_message)
        
        # Write to the terminal
        self.write(command, end='\n')
        # Read back from the terminal
        result = u''
        if command != '':
            result = self.read_until(command.splitlines()[0][0:20], timeout=3)
        result += self.read_until_regex(prompt, timeout)
        
        # Disable banner mode
        if self.banner:
            if self.prompt_matched or command.lstrip().startswith(self.banner):
                self.banner = False
                debug_message = 'banner mode off -- matched prompt or delimeter.'
                debug_display_info(debug=self.debug, message=debug_message)
        return result

    def send(self, command, prompt=None, timeout=None, send=True, end='\n'):
        """Sends a command to the terminal and waits for the prompt to return.
        
        Returns a string of output from the terminal.
        To receive back a list use " terminal.send('xyz').splitlines() "
        Optional prompt specifies the an expected prompt in regex format.
        Object.last_regex_match is assigned the string matching the prompt.
        Optional timeout specifies time in seconds to wait for the prompt.
        Optional send=False prevents the string from being sent.  This is
        useful when you want to verify what will be sent before sending.
        """
        debug_display_info(debug=self.debug)
        if not send:
            result = '[SEND=FALSE] {0}'.format(command)
        else:
            if prompt is None:
                prompt = self.prompt
            if timeout is None:
                timeout = self.timeout
            result = self._send_main(command, prompt=prompt, timeout=timeout, end=end)
        return result.splitlines()

    def set_logging(self, filename, mode=None):
        """Set logfile to capture terminal input and output

        Specify a filename to start logging.
        Specify None to stop logging.
        mode can be set to 'a' to append to an existing file.
        Default mode is 'w', which will overwrite any existing file.
        """
        debug_display_info(debug=self.debug)
        if not mode == 'a':
            mode = 'w'
        if filename is None:
            self.logfile = False
        else:
            with open(filename, mode) as logfile:
                self.logfile = filename

    def write_to_log(self, output, prefix=None):
        """Writes string to the current logging file if logging is enabled
        
        Accepts a string.
        Used internally, but useful for inserting debug comments.
        """
        if prefix is None:
            prefix = str(datetime.datetime.fromtimestamp(time.time()))
        if self.logfile:
            with open(self.logfile, 'a') as logfile:
                logfile.write(prefix + output)
                return True
        return False


class SSH(object):
    """Uses SSH protocol to access network device terminal."""

    # Should add all SSHclient options here as modified defaults
    # so that they can be modified by user prior to calling login.
    # Must consider possibility that Linuxer based NOS devices might support
    # identity files, and provide a way to specify that to this object.
    
    # TODO: Remove exception handling - exceptions should be handled 
    # by the library user.
    def __init__(self, host, **kwargs):
        self.debug = kwargs.get('debug', 0)
        debug_display_info(debug=self.debug)
        self.terminal_exceptions = (
            socket.timeout,
            socket.error,
            paramiko.BadHostKeyException,
            paramiko.AuthenticationException,
            paramiko.SSHException,
            )
        kwargs['look_for_keys'] = False  # Fix auth error due to private keys.
        kwargs['allow_agent'] = False    # Fix auth error from fedora desktop.
        if not 'timeout' in kwargs:
            kwargs['timeout'] = 7
        try:
            port = int(kwargs['port'])
            username = kwargs['username']
            password = kwargs['password']
        except KeyError as exception:
            print('Missing required argument: {0}'.format(exception),
                    file=sys.stderr)
        debug_display_info(debug=self.debug,
            message="SSH to host {0} : {1}".format(host, port))
        self.client = paramiko.SSHClient()
        self.client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        self.client.connect(host, **kwargs)
        self.terminal = self.client.invoke_shell()

    def _close(self):
        """Properly close connection to network device."""
        debug_display_info(debug=self.debug)
        if self.client:
            try:
                self.client.close()
                return True
            except self.terminal_exceptions as terminal_exception:
                print("terminal_close_exception: %s" % str(terminal_exception), file=sys.stderr)  ###
                return False

    def _read(self):
        """Internal method to get output from SSH session."""
        debug_display_info(debug=self.debug)
        read_buffer = bytes()
        try:
            while self.terminal.recv_ready():
                read_buffer += self.terminal.recv(16384)
            return read_buffer.decode()
        except self.terminal_exceptions as terminal_exception:
            print("terminal_read_exception: %s" % str(terminal_exception), file=sys.stderr)   ###
            return str(terminal_exception)

    def _write(self, text):
        """Internal method to write string to SSH session."""
        debug_display_info(debug=self.debug)
        try:
            # send a command to shell and get output back
            self.terminal.send(text)
            return True
        except self.terminal_exceptions as terminal_exception:
            print("terminal_write_exception: %s" % str(terminal_exception), file=sys.stderr)   ###
            return False


class Telnet(object):
    """Uses Telnet protocol to access network device terminal."""

    def __init__(self, host, **kwargs):
        self.debug = kwargs.get('debug', 0)
        debug_display_info(debug=self.debug)
        try:
            port = int(kwargs['port'])
            username = kwargs['username']
            password = kwargs['password']
            debug_display_info(debug=self.debug,
                message="Telnet to host {0} : {1}".format(host, port))
            self.terminal = telnetlib.Telnet(host, port)
        except KeyError as exception:
            raise KeyError('Missing required argument: {}'.format(exception))

    def _close(self):
        """Properly close connection to network device."""
        debug_display_info(debug=self.debug)
        try:
            self.terminal.close()
        except exceptions as exception:
            debug_display_info(debug=self.debug,
                message="terminal_close_exception: {0}".format(exception))
            return False

    def _read(self):
        """Internal method to get output from Telnet session."""
        ### ADD EXCEPTION ###
        debug_display_info(debug=self.debug)
        read_buffer = self.terminal.read_very_eager()
        return read_buffer.decode()

    def _write(self, text):
        """Internal method to send string to Telnet session."""
        ### ADD EXCEPTION ###
        debug_display_info(debug=self.debug)
        self.terminal.write(text.encode())
        return True

