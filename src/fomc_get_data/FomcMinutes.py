from datetime import datetime
import threading
import sys
import os
import pickle
import re
from itertools import chain
import requests
from bs4 import BeautifulSoup

import numpy as np
import pandas as pd

# Import parent class
from .FomcBase import FomcBase

def try_parsing_date(text):
    for fmt in ('%B-%d-%Y','%b-%d-%Y'):
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            pass
    raise ValueError('no valid date format found')

class FomcMinutes(FomcBase):
    '''
    A convenient class for extracting minutes from the FOMC website
    Example Usage:  
        fomc = FomcMinutes()
        df = fomc.get_contents()
    '''
    def __init__(self, verbose = True, max_threads = 10, base_dir = '../data/FOMC/'):
        super().__init__('minutes', verbose, max_threads, base_dir)

    def _get_links(self, from_year):
        '''
        Override private function that sets all the links for the contents to download on FOMC website
         from from_year (=min(2015, from_year)) to the current most recent year
        '''
        self.links = []
        self.titles = []
        self.speakers = []
        self.dates = []
        self.date_released = []
        self.date_meeting = []

        r = requests.get(self.calendar_url)
        soup = BeautifulSoup(r.text, 'html.parser')

        # Getting links from current page. Meetin scripts are not available.
        if self.verbose: print("Getting links for minutes...")
        contents = soup.find_all('a', href=re.compile('^/monetarypolicy/fomcminutes\d{8}.htm'))
        self.links = [content.attrs['href'] for content in contents]
        self.speakers = [self._speaker_from_date(self._date_from_link(x)) for x in self.links]
        self.titles = ['FOMC Meeting Minutes'] * len(self.links)
        self.dates = [datetime.strptime(self._date_from_link(x), '%Y-%m-%d') for x in self.links]
        # Get release dates for minutes
        # Date release
        # date_released = list(map('-'.join,re.findall('\(Released (\w*) (\d{1,2}), (\d{4})\)',r.text)))
        
        text = soup.find_all('div', {'class': re.compile(r'.*fomc-meeting__minutes')})
        date_released = list(chain(*[re.findall('\(Released (\w*) (\d{1,2}), (\d{4})\)',t.text) for t in text]))
        date_released = list(map('-'.join,date_released))
        date_released = [try_parsing_date(x) for x in date_released]
        self.date_released = self.date_released + date_released
        # # Date meeting
        # date_meeting = list(map('-'.join,re.findall('(\w*) (?:\d{1,2}-)(\d{1,2}) Meeting - (\d{4})',r.text)))
        # date_meeting = [try_parsing_date(x) for x in date_meeting]
        # self.date_meeting = self.date_meeting + date_meeting
        for year in range(from_year, 2017):
            fomc_yearly_url = self.base_url + '/monetarypolicy/fomchistorical' + str(year) + '.htm'
            r = requests.get(fomc_yearly_url)
            # Date release
            date_released = list(map('-'.join,re.findall('\(Released (\w*) (\d{1,2}), (\d{4})\)',r.text)))
            date_released = [try_parsing_date(x) for x in date_released]
            self.date_released = self.date_released + date_released
            # # Date meeting
            # date_meeting = list(map('-'.join,re.findall('(\w*) (?:\d{1,2}-)(\d{1,2}) Meeting - (\d{4})',r.text)))
            # date_meeting = [try_parsing_date(x) for x in date_meeting]
            # self.date_meeting = self.date_meeting + date_meeting
        # self.date_released = sorted(self.date_released)
        if self.verbose: print("{} links found in the current page.".format(len(self.links)))

        # Archived before 2015
        if from_year <= 2015:
            print("Getting links from archive pages...")
            for year in range(from_year, 2017):
                yearly_contents = []
                fomc_yearly_url = self.base_url + '/monetarypolicy/fomchistorical' + str(year) + '.htm'
                r_year = requests.get(fomc_yearly_url)
                soup_yearly = BeautifulSoup(r_year.text, 'html.parser')
                yearly_contents = soup_yearly.find_all('a', href=re.compile('(^/monetarypolicy/fomc\d+|^/monetarypolicy/fomcminutes|^/fomc/minutes|^/fomc/MINUTES)'))
                for yearly_content in yearly_contents:
                    self.links.append(yearly_content.attrs['href'])
                    self.speakers.append(self._speaker_from_date(self._date_from_link(yearly_content.attrs['href'])))
                    self.titles.append('FOMC Meeting Minutes')
                    self.dates.append(datetime.strptime(self._date_from_link(yearly_content.attrs['href']), '%Y-%m-%d'))
                    # Sometimes minutes carries the first day of the meeting before 2000, so update them to the 2nd day
                    if self.dates[-1] == datetime(1996,1,30):
                        self.dates[-1] = datetime(1996,1,31)
                    elif self.dates[-1] == datetime(1996,7,2):
                        self.dates[-1] = datetime(1996,7,3)
                    elif self.dates[-1] == datetime(1997,2,4):
                        self.dates[-1] = datetime(1997,2,5)
                    elif self.dates[-1] == datetime(1997,7,1):
                        self.dates[-1] = datetime(1997,7,2)
                    elif self.dates[-1] == datetime(1998,2,3):
                        self.dates[-1] = datetime(1998,2,4)
                    elif self.dates[-1] == datetime(1998,6,30):
                        self.dates[-1] = datetime(1998,7,1)
                    elif self.dates[-1] == datetime(1999,2,2):
                        self.dates[-1] = datetime(1999,2,3)
                    elif self.dates[-1] == datetime(1999,6,29):
                        self.dates[-1] = datetime(1999,6,30)

                if self.verbose: print("YEAR: {} - {} links found.".format(year, len(yearly_contents)))
        print("There are total ", len(self.links), ' links for ', self.content_type)

    def _add_article(self, link, index=None):
        '''
        Override a private function that adds a related article for 1 link into the instance variable
        The index is the index in the article to add to. 
        Due to concurrent prcessing, we need to make sure the articles are stored in the right order
        '''
        if self.verbose:
            sys.stdout.write(".")
            sys.stdout.flush()

        res = requests.get(self.base_url + link)
        html = res.text

        # p tag is not properly closed in many cases
        html = html.replace('<P', '<p').replace('</P>', '</p>')
        html = html.replace('<p', '</p><p').replace('</p><p', '<p', 1)

        # remove all after appendix or references
        x = re.search(r'(<b>references|<b>appendix|<strong>references|<strong>appendix)', html.lower())
        if x:
            html = html[:x.start()]
            html += '</body></html>'
        # Parse html text by BeautifulSoup
        article = BeautifulSoup(html, 'html.parser')

        #if link == '/fomc/MINUTES/1994/19940517min.htm':
        #    print(article)

        # Remove footnote
        for fn in article.find_all('a', {'name': re.compile('fn\d')}):
            # if fn.parent:
            #     fn.parent.decompose()
            # else:
            #     fn.decompose()
            fn.decompose()
        # # Get all p tag
        paragraphs = article.findAll('p')
        self.articles[index] = "\n\n[SECTION]\n\n".join([paragraph.get_text().strip() for paragraph in paragraphs])
        # Replace findAll with find to avoid duplicates
        # if len(article.find('p')) == 1:
        #     paragraphs = article.findAll('p')
        # else:
        #     paragraphs = article.find('p')
        # self.articles[index] = "\n\n[SECTION]\n\n".join([paragraph.get_text().strip() for paragraph in paragraphs])