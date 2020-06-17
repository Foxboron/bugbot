#! /usr/bin/env python3
# -*- coding: utf-8 -*-

import random, time, subprocess
import ssl
from itertools import *

import irc
import irc.bot
import irc.strings
from irc.client import ip_numstr_to_quad, ip_quad_to_numstr

from queue import Queue
from http.cookiejar import CookieJar
import urllib.request, urllib.parse, urllib.error, urllib.request, urllib.error, urllib.parse
from urllib.request import urlopen, Request, HTTPRedirectHandler, HTTPHandler, HTTPSHandler, HTTPCookieProcessor, build_opener
from urllib.parse import urlencode, quote
from urllib.error import URLError, HTTPError

from bs4 import BeautifulSoup

debug = False

short_time = lambda: time.strftime('%a-%H:%M:%S', time.localtime())

pull = lambda url: urlopen(Request(url)).read()

# todo: 'more' option for next search result
#       mailing list URLs
#       re-enable private channel (#archlinux-tu) login
#       re-enable polling rate changes

mailmen = [('aur-general', 'https://mailman.archlinux.org/pipermail/aur-general/%Y-%B/date.html')]
bt = None
ml = None
bot = None

irc_host = 'chat.freenode.net'
#irc_host = '127.0.0.1'
irc_port = 6697
irc_channel = '#archlinux-bugs'
irc_username = 'arch-bugbot'
nickserv_identify = ''
bugtracker_user = ''
bugtracker_pass = ''
admin_nicks = ['keenerd', 'falconindy']
poll_interval = 10  # minutes
april_fools = False
soup_parse = 'lxml'

class TestBot(irc.bot.SingleServerIRCBot):
    def __init__(self):

        self.ssl_factory = irc.connection.Factory(wrapper=ssl.wrap_socket)

        irc.bot.SingleServerIRCBot.__init__(self, [(irc_host, irc_port)],
                                            irc_username, irc_username,
                                            reconnection_interval=2,
                                            connect_factory=self.ssl_factory)
        self.channel = irc_channel
        #if conf.password:
        #    self.server_list[0].password = conf.password
        #self.connection.add_global_handler(302, self.on_userhost)
        self.mute = False
        self.recurring_interval = 0

    def on_userhost(self, c, e):
        user,_,host = e.arguments[0].partition('=+')
        user = user.strip()
        host = host.strip()
        stateful.userhosts[user] = host

    def on_nicknameinuse(self, c, e):
        c.nick(c.get_nickname() + "_")

    def on_welcome(self, c, e):
        print('signing in...')
        time.sleep(3)
        c.privmsg('NickServ', "identify " + nickserv_identify)
        #if conf.channel_key:
        #    c.join(self.channel, key=conf.channel_key)
        #else:
        #    c.join(self.channel)
        time.sleep(3)
        c.join(self.channel)
        print('sign in finished')

    def on_privmsg(self, c, e):
        handle_message(True, c, e)

    def on_pubmsg(self, c, e):
        handle_message(False, c, e)
        
    def send(self, message, chan=None, mute_override=False):
        print(short_time(), chan, message)
        if debug:
            return
        if self.mute and not mute_override:
            return
        if chan is None:
            chan = self.channel
        self.connection.privmsg(chan, message)

    def toggle_mute(self):
        self.mute = not self.mute
        self.send('Bugbot %smuted.' % ('un', '')[self.mute], mute_override=True)

    def recurring(self, interval, fn):
        self.recurring_interval = interval
        # syntax change between irc lib versions
        if 'ircobj' in dir(self) and 'execute_every' in dir(self.ircobj):
            self.ircobj.execute_every(interval, fn)
        elif 'connection' in dir(self) and 'execute_every' in dir(self.connection):
            self.connection.execute_every(interval, fn)
        elif 'reactor' in dir(self) and 'execute_every' in dir(self.reactor.scheduler):
            self.reactor.scheduler.execute_every(period=interval, func=fn)
        else:
            raise

def handle_message(priv, connection, event):
    chan = event.target
    nick = event.source.nick
    text = event.arguments[0]
    if not priv:
        #sendto = None
        sendto = chan
    else:
        sendto = nick
    if not any(text.startswith(prefix) for prefix in ['bugbot ', 'arch-bugbot: ', 'arch-bugbot ']):
        return
    text = text.partition(' ')[2].strip()
    command, _, text = text.partition(' ')
    text = text.strip()
    give = ''
    if command == 'give':
        give, _, text = text.partition(' ')
        text = text.strip()
        command, _, text = text.partition(' ')
        text = text.strip()
        give = give + ': '
    if command == 'help':
        bot.send(give + 'Commands: bugbot \x02help\x02 | \x02todo\x02 BUGID | \x02search\x02 [--arch|aur|comm|pacman|release|closed|nick|url] QUERY | \x02random\x02 [QUERY] | \x02mute\x02 | \x02interval\x02 [MINUTES] | \x02give\x02 USER ...', chan=sendto)
    if command == 'todo':
        bot.send(give + check_todo(text), chan=sendto)
    if command == 'random':
        bot.send(give + random_search(text), chan=sendto)
    if command == 'search':
        bot.send(give + recent_search(text), chan=sendto)
    if nick not in admin_nicks:
        return
    # awkward, these will report on #al-bugs
    if command == 'mute':
        bot.toggle_mute()
    if command == 'interval':
        #bot.set_interval(text)
        bot.send('Disabled because this irclib is annoying.', chan=sendto)

def extract(soupy):
    "dance to avoid memory leaks"
    #if type(soupy) == unicode:
    #    return unicode(soupy).encode('utf-8')
    #return unicode(soupy.extract()).encode('utf-8')
    if type(soupy) == str:
        return str(soupy)
    return str(soupy.extract())

class Bugtracker(object):
    def __init__(self):
        self.user = bugtracker_user
        self.password = bugtracker_pass
        self.login_page = 'https://bugs.archlinux.org/index.php?do=authenticate'
        #self.target_page = 'http://bugs.archlinux.org/index.php?events%5B%5D=1&events%5B%5D=13&events%5B%5D=2&events%5B%5D=4&event_number=50&do=reports'
        #self.target_page = 'http://bugs.archlinux.org/index.php?events[]=1&events[]=13&events[]=2&events[]=4&fromdate=&todate=&event_number=50&project=0&do=reports&submit='
        self.target_page = 'https://bugs.archlinux.org/index.php?events%5B%5D=1&events%5B%5D=13&events%5B%5D=2&events%5B%5D=4&event_number=50&do=reports&project=0'
        self.cj = CookieJar()
        self.opener = build_opener(
            HTTPRedirectHandler(),
            HTTPHandler(debuglevel=0),
            HTTPSHandler(debuglevel=0),
            HTTPCookieProcessor(self.cj)
        )
        #self.opener.addheaders = [
        #    ('User-agent', ('Mozilla/4.0 (compatible; MSIE 6.0; '
        #                   'Windows NT 5.2; .NET CLR 1.1.4322)'))
        #]
        self.opener.addheaders = [('User-agent', 'Mozilla/5.0')]

        # need this twice - once to set cookies, once to log in...
        self.login()
        #self.login()
        self.old_events = set([])

    def login(self):
        "handle login, populate the cookie jar"
        login_data = bytes(urlencode({
            'user_name' : self.user,
            'password' : self.password,
            'remember_login' : 'on',
            #'return_to' : None,
        }), 'utf-8')
        response = self.opener.open(self.login_page, login_data, timeout=10)
        return ''.join(str(s) for s in response.readlines())
    def get_recent(self):
        while True:
            try:
                response = self.opener.open(self.target_page)
                break
            except URLError:
                print('Failed request')
                time.sleep(10)
        html = ''.join(str(s) for s in response.readlines())
        soup = BeautifulSoup(html, features=soup_parse)
        body = soup.html.body
        tasks = body.find(**{'id': 'tasklist_table'}).findAll('tr')[1:]
        results = []
        for t in tasks:
            t = t.findAll('td')
            try:
                user2 = extract(t[1].a.contents[0])
                user3 = user2.partition('(')[2].partition(')')[0]
                if user3 in ('wonder',):  # hates everything
                    user3 = user2.partition('(')[0].strip()
            except:
                user3 = "Anon"
            results.append({'event':   extract(t[0].contents[0]),
                            #'user':    extract(t[1].a.contents[0]),  # breaks with non-linked "Anonymous Submitter"
                            'user':    user3,
                            'date':    extract(t[2].contents[0]),
                            'url':     extract(t[3].a['href'].partition('?')[0]),
                            'status':  extract(t[3].a['title']),
                            'summary': extract(t[3].a.contents[0]),
                           })
        soup.decompose()
        return results
    def clean_misc(self, event):
        "remove waste of ascii"
        for k,v in event.items():
            event[k] = str(v)
        if event['status'].endswith(' | 100%'):
            event['status'] = event['status'][:-7]
        if event['status'].endswith(' | 0%'):
            event['status'] = event['status'][:-5]
        return event
    def update_history(self):
        self.old_events = set((t['url'], t['date']) for t in self.get_recent())


class MailingList(object):
    def __init__(self, name, url):
        "url should include strftime formatting"
        self.name = name
        self.url = url
        #self.interval = 10
        #self.next_tick = time.time() + self.interval * 60
        self.update_history(self.all_events(self.download()))
    def download(self):
        try:
            return pull(time.strftime(self.url, time.localtime()))
        except HTTPError:
            return ""
    def all_events(self, html):
        "returns (author, title, href)"
        if not html:
            raise StopIteration
        soup = BeautifulSoup(html, features=soup_parse)
        body = soup.html.body
        messages = body.findAll('li')[2:-2]
        for m in messages:
            author = extract(m.i.contents[0]).strip()
            title = extract(m.a.contents[0]).strip()
            href = extract(m.a['href']).strip()
            yield author, title, href
    def update_history(self, events):
        "must be called after new_events()"
        self.history = set()
        for _,_,href in events:
            self.history.add(href)
    def new_events(self, events):
        for author, title, href in events:
            if href in self.history:
                continue
            yield author, title, href
    def pretty(self, event):
        # todo, make less fragile
        author, title, href = event
        text = title.replace('[%s]' % self.name, '[%s, %s]' % (str(self.name), author))
        url = time.strftime(self.url, time.localtime())
        url = url.replace('date.html', href)
        return text + ' | ' + str(url)
    def tick(self):
        "call every minute, returns pretty lines"
        #if time.time() < self.next_tick:
        #    raise StopIteration
        html = self.download()
        events = self.new_events(self.all_events(html))
        for e in events:
            yield self.pretty(e)
        self.update_history(self.all_events(html))
        #self.next_tick += self.interval * 60

def random_search(query=None):
    search = "https://bugs.archlinux.org/index/proj0?do=index&project=0&search_in_comments=1&search_in_details=1&search_for_all=1&status%%5B%%5D=open&pagenum=%i&string=%s"
    if query is None:
        query = ''
    page1 = pull(search % (1, quote(query)))
    soup = BeautifulSoup(page1, features=soup_parse)
    body = soup.html.body
    count = extract(body.find(**{'id': 'taskrange'}).contents[0])
    if "Your search returned no results." in count:
        soup.decompose()
        return "The search returned no results."
    count = int(count.strip().split(' ')[-1])
    #i = random.randint(1, count)  # off by one might start here
    i = random.randrange(count)
    page = i//20 + 1
    element = (i % 20) + 1
    if i != 1:
        pageN = pull(search % (page, quote(query)))
        soup.decompose()
        soup = BeautifulSoup(pageN, features=soup_parse)
        body = soup.html.body
    hit = body.find(**{'id': 'tasklist_table'}).findAll('tr')[element]  # off by one?
    number = extract(hit(**{'class':"task_id"})[0].a.contents[0])
    soup.decompose()
    return 'https://bugs.archlinux.org/task/%s' % number

def recent_search(query=None):
    #search = "https://bugs.archlinux.org/index/proj0?do=index&project=0&search_in_comments=1&search_in_details=1&search_for_all=1&status%%5B%%5D=open&pagenum=%i&string=%s"
    search = "https://bugs.archlinux.org/index.php?do=index&project=%i&search_in_comments=1&search_in_details=1&search_for_all=1&status=%s&pagenum=%i&string=%s&dev=%s"
    user_search = "https://bugs.archlinux.org/index.php?do=index&project=%i&status=%s&dev=%s"
    proj_id = 0
    status = 'open'
    user = ''
    return_link = False
    while query.startswith('--'):
        proj, _, query = query.partition(' ')
        proj_lut = {'--all':0, '--arch':1, '--aur':2, '--comm':5, '--pacman':3, '--release':6}
        if proj in proj_lut:
            proj_id = proj_lut[proj]
        elif proj == '--closed':
            status = 'closed'
        elif proj == '--nick':
            user, _, query = query.partition(' ')
        elif proj == '--url':
            return_link = True
        else:
            query = proj + ' ' + query
            break
    if query is None:
        query = ''
    if query == '' and user == '':
        return "Needs a search query."
    if user and not query:
        return user_search % (proj_id, status, quote(user))
    search_url = search % (proj_id, status, 1, quote(query), quote(user))
    if return_link:
        return search_url
    page1 = pull(search_url)
    soup = BeautifulSoup(page1, features=soup_parse)
    body = soup.html.body
    count = extract(body.find(**{'id': 'taskrange'}).contents[0])
    if "Your search returned no results." in count:
        soup.decompose()
        return "Your search returned no results."
    hit = body.find(**{'id': 'tasklist_table'}).findAll('tr')[1]
    number = extract(hit(**{'class':"task_id"})[0].a.contents[0])
    title  = extract(hit(**{'class':"task_id"})[0].a['title'])
    soup.decompose()
    return 'https://bugs.archlinux.org/task/%s (%s)' % (number, title)


def pretty(*event):
    #return '!ignore [%s] %s | %s' % event
    return '[\x02%s\x02, %s] %s |\x0311 %s \x03' % event

def check_todo(bugid):
    "hacky scope"
    try:
        todohtml = pull('https://wiki.archlinux.org/index.php/Bug_Day_TODO')
        if '>FS#'+bugid+'</a>' in todohtml:
            return 'Bug seems to be already on the TODO list'
        bugpage = 'https://bugs.archlinux.org/task/%s' % bugid
        bughtml = pull(bugpage)
        soup = BeautifulSoup(bughtml, features=soup_parse)
        title = extract(soup.html.head.title.string)
        title = title.split(':')[1].strip()
        #return '!ignore [not found] %s %s' % (bugpage, title)
        return '[not found] %s %s' % (bugpage, title)
    except:
        return 'Something is broken...'

def call_stdout(cmd):
    spp = subprocess.PIPE
    subp = subprocess.Popen(cmd, shell=False, stdin=None, stdout=spp)
    return str(subp.communicate()[0], 'utf-8')

def bofh():
    return call_stdout(['fortune', 'bofh-excuses']).strip().split('\n')[-1].strip().strip('.').lower()

def too_quiet():
    t = random.choice(['Closed', 'Comment'])
    m = random.choice(['Unconfirmed', 'Not a bug', 'Fixed', 'Assigned', 'Implemented', 'WontFix'])
    p = random.choice(call_stdout(['pacman', '-Slq', 'core']).split('\n'))
    b = bofh()
    u = random.randint(60000, 80000)
    #return '!ignore [%s] %s | [%s] %s | https://bugs.archlinux.org/task/%i' % (t, m, p, b, u)
    # needs random dev/tu nick
    return '[\x02%s\x02] %s | [%s] %s |\x0311 https://bugs.archlinux.org/task/%i \x03' % (t, m, p, b, u)

def polling():
    redundant = set([])  # Avoid sending similar messages 
    # in same burst.  Should say "x 3" to indicate.
    noisy = False
    for t in reversed(list(bt.get_recent())):
        t = bt.clean_misc(t)
        sig = (t['url'], t['date'])
        if sig in bt.old_events:
            continue
        bt.old_events.add(sig)
        summary = (t['url'], t['event'])
        if summary in redundant:
            continue
        noisy = True
        redundant.add(summary)
        if 'PLEASE ENTER SUMMARY' in t['status']:
            t['status'] = t['status'].replace('PLEASE ENTER SUMMARY', bofh())
        t['event']  = t['event'].replace('Comment added', 'Comment')
        try:
            bot.send(pretty(t['event'], t['user'], t['status'], t['url']))
        except UnicodeEncodeError:
            print('fix unicode')
        time.sleep(1)
    # weird place to do this, fix scheduling
    for m in ml.tick():
        try:
            bot.send(m, irc_channel)
        except UnicodeEncodeError:
            print('fix unicode')
        time.sleep(1)
    if april_fools and not noisy and random.random() < (poll_interval / 1440.0):
        bot.send(too_quiet())

def main():
    global bt, ml, bot
    bt = Bugtracker()
    ml = MailingList(*mailmen[0])
    if not debug:
        bt.update_history()
    bot = TestBot()
    bot.recurring(poll_interval*60, polling)
    bot.start()

if __name__ == '__main__':
    while True:
        try:
            main()
        except KeyboardInterrupt:
            break
        except:
            if debug:
                raise
            print('Crashed, restarting.')
        time.sleep(60)





