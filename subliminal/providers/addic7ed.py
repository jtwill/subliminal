# -*- coding: utf-8 -*-
from __future__ import unicode_literals
import logging
import re
import unicodedata
import babelfish
import bs4
import requests
from . import Provider
from .. import __version__
from ..cache import region, SHOW_EXPIRATION_TIME
from ..exceptions import ConfigurationError, AuthenticationError, DownloadLimitExceeded, ProviderError
from ..subtitle import Subtitle, fix_line_endings, compute_guess_properties_matches, hmg, rm_par
from ..video import Episode


logger = logging.getLogger(__name__)
babelfish.language_converters.register('addic7ed = subliminal.converters.addic7ed:Addic7edConverter')


class Addic7edSubtitle(Subtitle):
    provider_name = 'addic7ed'

    def __init__(self, language, series, season, episode, title, year, version, hearing_impaired, download_link,
                 page_link):
        super(Addic7edSubtitle, self).__init__(language, hearing_impaired, page_link)
        self.series = series
        self.season = season
        self.episode = episode
        self.title = title
        self.year = year
        self.version = version
        self.download_link = download_link

    def compute_matches(self, video):
        matches = set()
        # series
        if video.series is not None and hmg(video.series) == hmg(self.series):
            matches.add('series')
        # season
        if video.season is not None and self.season == video.season:
            matches.add('season')
        # episode
        if video.episode is not None and self.episode == video.episode:
            matches.add('episode')
        # title
        if video.title is not None and hmg(video.title) == hmg(self.title):
            matches.add('title')
        # year
        if self.year == video.year:
            matches.add('year')
        # release_group
        if video.release_group is not None and self.version is not None and video.release_group.lower() in self.version.lower():
            matches.add('release_group')
        # resolution
        if video.resolution is not None and self.version is not None and video.resolution.lower() in self.version.lower():
            matches.add('resolution')
        # format
        if video.format is not None and self.version is not None and video.format.lower() in self.version.lower():
            matches.add('format')
        # we don't have the complete filename, so we need to guess the matches separately
        # guess resolution (screenSize in guessit)
        logger.debug("About to guess with version=%s, matches %r", self.version, matches)
        matches |= compute_guess_properties_matches(video, self.version, 'screenSize')
        # guess format
        matches |= compute_guess_properties_matches(video, self.version, 'format')
        logger.debug("Finished guessing with version=%s, matches %r", self.version, matches)
        return matches


class Addic7edProvider(Provider):
    languages = {babelfish.Language('por', 'BR')} | {babelfish.Language(l)
                 for l in ['ara', 'aze', 'ben', 'bos', 'bul', 'cat', 'ces', 'dan', 'deu', 'ell', 'eng', 'eus', 'fas',
                           'fin', 'fra', 'glg', 'heb', 'hrv', 'hun', 'hye', 'ind', 'ita', 'jpn', 'kor', 'mkd', 'msa',
                           'nld', 'nor', 'pol', 'por', 'ron', 'rus', 'slk', 'slv', 'spa', 'sqi', 'srp', 'swe', 'tha',
                           'tur', 'ukr', 'vie', 'zho']}
    video_types = (Episode,)
    server = 'http://www.addic7ed.com'
    
    def __init__(self, username=None, password=None):
        if username is not None and password is None or username is None and password is not None:
            raise ConfigurationError('Both username and password must be specified, or both None')
        self.username = username
        self.password = password
        self.logged_in = False

    def initialize(self):
        self.session = requests.Session()
        self.session.headers = {'User-Agent': 'Subliminal/%s' % __version__.split('-')[0]}
        # login, unless username and password are both None
        if self.username is not None and self.password is not None:
            logger.debug('Logging in')
            data = {'username': self.username, 'password': self.password, 'Submit': 'Log in'}
            r = self.session.post(self.server + '/dologin.php', data, timeout=10, allow_redirects=False)
            if r.status_code == 302:
                logger.info('Logged in')
                self.logged_in = True
            else:
                raise AuthenticationError(self.username)

    def terminate(self):
        # logout
        if self.logged_in:
            r = self.session.get(self.server + '/logout.php', timeout=10)
            logger.info('Logged out')
            if r.status_code != 200:
                raise ProviderError('Request failed with status code %d' % r.status_code)
        self.session.close()

    def get(self, url, params=None):
        """Make a GET request on `url` with the given parameters

        :param string url: part of the URL to reach with the leading slash
        :param params: params of the request
        :return: the response
        :rtype: :class:`bs4.BeautifulSoup`

        """
        r = self.session.get(self.server + url, params=params, timeout=10)
        if r.status_code != 200:
            raise ProviderError('Request failed with status code %d' % r.status_code)
        return bs4.BeautifulSoup(r.content, ['permissive'])

    @region.cache_on_arguments(expiration_time=SHOW_EXPIRATION_TIME)
    def get_show_ids(self):
        """Load the shows page with default series to show ids mapping

        :return: series to show ids
        :rtype: dict

        """
        soup = self.get('/shows.php')
        show_ids = {}
        iii = 0
        for html_show in soup.select('td.version > h3 > a[href^="/show/"]'):
            iii += 1
            show_str = html_show.string
            show_code = int(html_show['href'][6:])
            show_ids[show_str.lower()] = show_code 
            show_ids[clean_series(show_str)] = show_code
        logger.info('Addic7ed show list length = %d', iii)
        return show_ids

    @region.cache_on_arguments(expiration_time=SHOW_EXPIRATION_TIME)
    def find_show_id(self, series, year=None):
        """Find the show id from the `series` with optional `year`

        Use this only if the show id cannot be found with :meth:`get_show_ids`

        :param string series: series of the episode in lowercase
        :param year: year of the series, if any
        :type year: int or None
        :return: the show id, if any
        :rtype: int or None

        """
        series_year = series
        if year is not None:
            series_year += ' (%d)' % year
        params = {'search': series_year, 'Submit': 'Search'}
        logger.debug('Searching series %r', params)
        suggested_shows = self.get('/search.php', params).select('span.titulo > a[href^="/show/"]')
        if not suggested_shows:
            logger.info('Series %r not found', series_year)
            return None
        suggested_list = [ss['href'][6:] for ss in suggested_shows]
        logger.debug('suggested_shows length = %d; %r', len(suggested_list), suggested_list)
        return int(suggested_shows[0]['href'][6:])

    def query(self, languages, series, season, episode, year=None):
        show_ids = self.get_show_ids()
        logger.info('Addic7ed augmented show list length = %d', len(show_ids)) 
        show_id = None
        if year is not None:  # search with the year
            sub_year = year
            # before appending year, remove existing (...) , eg. (US)
            series_fix = rm_par(series.lower()) + ' (%d)' % year
            series_clean = clean_series(series_fix)
            logger.debug('Looking up series "%s" or "%s"', series_fix, series_clean)
            if series_fix in show_ids:
                show_id = show_ids[series_fix]
                sub_series = series_fix
            elif series_clean in show_ids:
                show_id = show_ids[series_clean]
                sub_series = series_clean
            else:  # fallback to searching addic7ed server
                show_id = self.find_show_id(series_fix)
                sub_series = series_fix
                if show_id is None:  
                    show_id = self.find_show_id(series_clean)
                    sub_series = series_clean
        if show_id is None:  # if found nothing, try without year
            sub_year = None
            series_fix = series.lower()
            series_clean = clean_series(series_fix)
            logger.debug('Looking up series "%s" or "%s"', series_fix, series_clean)
            if series_fix in show_ids:
                show_id = show_ids[series_fix]
                sub_series = series_fix
            elif series_clean in show_ids:
                show_id = show_ids[series_clean]
                sub_series = series_clean
            else:  # fallback to searching addic7ed server
                show_id = self.find_show_id(series_fix)
                sub_series = series_fix
                if show_id is None:  
                    show_id = self.find_show_id(series_clean)
                    sub_series = series_clean
        if show_id is None:  # if found nothing, try removing (...) 
            series_fix = rm_par(series.lower())
            if series_fix == series.lower(): # give up if no (...) in series
                return []
            series_clean = clean_series(series_fix)
            logger.debug('Looking up series "%s" or "%s"', series_fix, series_clean)
            if series_fix in show_ids:
                show_id = show_ids[series_fix]
                sub_series = series_fix
            elif series_clean in show_ids:
                show_id = show_ids[series_clean]
                sub_series = series_clean
            else:  # fallback to searching addic7ed server
                show_id = self.find_show_id(series_fix)
                sub_series = series_fix
                if show_id is None:  
                    show_id = self.find_show_id(series_clean)
                    sub_series = series_clean
        if show_id is None:
            return []
        params = {'show_id': show_id, 'season': season}
        logger.debug('Searching subtitles for "%s" with %r', sub_series, params)
        link = '/show/{show_id}&season={season}'.format(**params)
        soup = self.get(link)
        subtitles = []
        iii = 0
        for row in soup('tr', class_='epeven completed'):
            cells = row('td')
            sub_status = cells[5].string
            if sub_status != 'Completed':
                continue    # skip if subtitle is not complete on server
            sub_language_str = cells[3].string
            if sub_language_str is not None and sub_language_str != "":
                sub_language = babelfish.Language.fromaddic7ed(sub_language_str)
            else:
                continue    # skip if no language
            sub_season_str = cells[0].string
            sub_episode_str = cells[1].string
            if sub_season_str is not None and sub_episode_str is not None:
                sub_season = int(sub_season_str)
                sub_episode = int(sub_episode_str)
            else:
                continue    # skip unless we have season and episode 
            if sub_episode != episode or sub_language not in languages:
                continue    # skip if wrong episode or unwanted language
            sub_title = cells[2].string
            sub_version = cells[4].string
            sub_hearing_impaired = bool(cells[6].string)
            sub_corrected = bool(cells[7].string)
            sub_hd = bool(cells[8].string)
            sub_download_link = cells[9].a['href']
            sub_page_link = self.server + cells[2].a['href']
            iii += 1
            logger.debug('addic7ed #%d: %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s',
                iii, sub_season_str, sub_episode_str, sub_title, sub_language_str,
                sub_version, sub_status, sub_hearing_impaired, sub_corrected,
                sub_hd, sub_download_link, sub_page_link
                )
            subtitles.append(Addic7edSubtitle(
                sub_language, sub_series, sub_season, sub_episode, sub_title, sub_year,
                sub_version, sub_hearing_impaired, sub_download_link, sub_page_link)
                )
        return subtitles

    def list_subtitles(self, video, languages):
        logger.debug('Listing subtitles for video %r; languages %r', video, languages)
        return [s for s in self.query(languages, video.series, video.season, video.episode, video.year)]

    def download_subtitle(self, subtitle):
        r = self.session.get(self.server + subtitle.download_link, timeout=10, headers={'Referer': subtitle.page_link})
        if r.status_code != 200:
            raise ProviderError('Request failed with status code %d' % r.status_code)
        if r.headers['Content-Type'] == 'text/html':
            raise DownloadLimitExceeded
        subtitle.content = fix_line_endings(r.content)

def clean_series(series_str):
    """Clean series name of some symbol characters, multiple spaces, 
    convert non-ASCII characters, and make lowercase
    """
    # convert non-ASCII characters to closest ASCII equivalents
    filtered_str = unicode(unicodedata.normalize('NFKD', series_str).encode('ascii','ignore'))
    return re.sub('[ ]{2,}', ' ',                     # compress multiple spaces to one space 
               re.sub(r"[?!.',/:-]+", '',             # remove ?!.',/:- chars ('-' last in [])
                   re.sub('&', 'and', filtered_str)   # replace '&' with 'and'
               )
           ).lower() 

