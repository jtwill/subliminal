# -*- coding: utf-8 -*-
from __future__ import unicode_literals
import base64
import logging
import os
import re
import zlib
import babelfish
import guessit
from . import Provider
from .. import __version__
from ..compat import ServerProxy, TimeoutTransport
from ..exceptions import ProviderError, AuthenticationError, DownloadLimitExceeded
from ..subtitle import Subtitle, fix_line_endings, compute_guess_matches, hmg, rm_par
from ..video import Episode, Movie


logger = logging.getLogger(__name__)


class OpenSubtitlesSubtitle(Subtitle):
    provider_name = 'opensubtitles'
    series_re = re.compile('^"(?P<series_name>.*)" (?P<series_title>.*)$')

    def __init__(self, language, hearing_impaired, id, matched_by, movie_kind, hash, movie_name, movie_release_name,  # @ReservedAssignment
                 movie_year, movie_imdb_id, series_season, series_episode, page_link):
        super(OpenSubtitlesSubtitle, self).__init__(language, hearing_impaired, page_link)
        self.id = id
        self.matched_by = matched_by
        self.movie_kind = movie_kind
        self.hash = hash
        self.movie_name = movie_name
        self.movie_release_name = movie_release_name
        self.movie_year = movie_year
        self.movie_imdb_id = movie_imdb_id
        self.series_season = series_season
        self.series_episode = series_episode

    @property
    def series_name(self):
        return self.series_re.match(self.movie_name).group('series_name')

    @property
    def series_title(self):
        return self.series_re.match(self.movie_name).group('series_title')

    def compute_matches(self, video):
        matches = set()
        # hash
        if 'opensubtitles' in video.hashes and self.hash == video.hashes['opensubtitles']:
            matches.add('hash')
        # imdb_id
        if video.imdb_id is not None and video.imdb_id == self.movie_imdb_id:
            matches.add('imdb_id')
        # Episode
        if isinstance(video, Episode) and self.movie_kind == 'episode':
            # series
            if video.series is not None and hmg(video.series) == hmg(self.series_name):
                matches.add('series')
            # year: no use matching year since opensubtitles returns the episode airdate year 
            # season number
            if video.season is not None and video.season == self.series_season:
                matches.add('season')
            # episode number
            if video.episode is not None and video.episode == self.series_episode:
                matches.add('episode')
            # title
            if video.title is not None and hmg(video.title) == hmg(self.series_title):
                matches.add('title')
            # guess
            logger.debug('About to guess release %s; with matches %r', self.movie_release_name, matches)
            matches |= compute_guess_matches(video, guessit.guess_episode_info(self.movie_release_name + '.mkv'))
            logger.debug('Finished guessing release %s; with matches %r', self.movie_release_name, matches)
        # Movie
        elif isinstance(video, Movie) and self.movie_kind == 'movie':
            # title
            if video.title is not None and hmg(video.title) == hmg(self.movie_name):
                matches.add('title')
            # year
            if video.year is not None and video.year == self.movie_year:
                matches.add('year')
            # guess
            logger.debug('About to guess release %s; with matches %r', self.movie_release_name, matches)
            matches |= compute_guess_matches(video, guessit.guess_movie_info(self.movie_release_name + '.mkv'))
            logger.debug('Finished guessing release %s; with matches %r', self.movie_release_name, matches)
        else:
            logger.info('%r is not a valid movie_kind for %r', self.movie_kind, video)
            return matches
        return matches


class OpenSubtitlesProvider(Provider):
    languages = {babelfish.Language.fromopensubtitles(l) for l in babelfish.language_converters['opensubtitles'].codes}

    def __init__(self):
        self.server = ServerProxy('http://api.opensubtitles.org/xml-rpc', transport=TimeoutTransport(10))
        self.token = None

    def initialize(self):
        response = checked(self.server.LogIn('', '', 'eng', 'subliminal v%s' % __version__.split('-')[0]))
        self.token = response['token']

    def terminate(self):
        checked(self.server.LogOut(self.token))
        self.server.close()

    def no_operation(self):
        checked(self.server.NoOperation(self.token))

    def query(self, languages, hash=None, size=None, imdb_id=None, query=None, season=None, episode=None):  # @ReservedAssignment
        searches = []
        if hash is not None and size is not None:
            searches.append({'moviehash': hash, 'moviebytesize': str(size)})
        if imdb_id is not None:
            searches.append({'imdbid': imdb_id})
        if query is not None and season is not None and episode is not None:
            searches.append({'query': rm_par(query), 'season': season, 'episode': episode})
        elif query is not None:
            searches.append({'query': query})
        if not searches:
            raise ValueError('One or more parameter missing')
        for search in searches:
            search['sublanguageid'] = ','.join(l.opensubtitles for l in languages)
        logger.debug('Searching subtitles %r', searches)
        response = checked(self.server.SearchSubtitles(self.token, searches))
        if not response['data']:
            logger.debug('No subtitles found')
            return []
        subtitles = []
        iii = 0
        for rsp in response['data']:
            iii += 1
            logger.debug(
                'opensubtitles #%d: SubAddDate %s; SubLanguageID %s; SubHearingImpaired %s; MatchedBy %s; '
                'MovieKind %s; MovieHash %s; MovieName %s; MovieReleaseName %s; ' 
                'MovieYear %s; MovieFPS %s; IDMovieImdb  %s; SeriesIMDBParent %s; '
                'SeriesSeason %s; SeriesEpisode %s',
                iii, rsp['SubAddDate'], rsp['SubLanguageID'], rsp['SubHearingImpaired'], rsp['MatchedBy'], 
                rsp['MovieKind'], rsp['MovieHash'], rsp['MovieName'], rsp['MovieReleaseName'], 
                rsp['MovieYear'], rsp['MovieFPS'], rsp['IDMovieImdb'], rsp['SeriesIMDBParent'], 
                rsp['SeriesSeason'], rsp['SeriesEpisode'] 
                )
            subtitles.append( 
                OpenSubtitlesSubtitle( 
                    babelfish.Language.fromopensubtitles(rsp['SubLanguageID']),
                    bool(int(rsp['SubHearingImpaired']) ), 
                    rsp['IDSubtitleFile'], 
                    rsp['MatchedBy'],
                    rsp['MovieKind'], 
                    rsp['MovieHash'], 
                    rsp['MovieName'], 
                    rsp['MovieReleaseName'],
                    int(rsp['MovieYear']) if rsp['MovieYear'] is not None else None, 
                    int(rsp['IDMovieImdb']) if rsp['IDMovieImdb'] is not None else None,
                    int(rsp['SeriesSeason']) if rsp['SeriesSeason'] is not None else None,
                    int(rsp['SeriesEpisode']) if rsp['SeriesEpisode'] is not None else None, 
                    rsp['SubtitlesLink']
                    ) 
                )
        return subtitles

    def list_subtitles(self, video, languages):
        query = None
        season = None
        episode = None
        if ('opensubtitles' not in video.hashes or not video.size) and not video.imdb_id:
            query = video.name.split(os.sep)[-1]
        if isinstance(video, Movie):
            query = video.title
        if isinstance(video, Episode):
            query = video.series
            season = video.season
            episode = video.episode
        return self.query(languages, hash=video.hashes.get('opensubtitles'), size=video.size, imdb_id=video.imdb_id,
                          query=query, season=season, episode=episode)

    def download_subtitle(self, subtitle):
        response = checked(self.server.DownloadSubtitles(self.token, [subtitle.id]))
        if not response['data']:
            raise ProviderError('Nothing to download')
        subtitle.content = fix_line_endings(zlib.decompress(base64.b64decode(response['data'][0]['data']), 47))


class OpenSubtitlesError(ProviderError):
    """Base class for non-generic :class:`OpenSubtitlesProvider` exceptions"""


class Unauthorized(OpenSubtitlesError, AuthenticationError):
    """Exception raised when status is '401 Unauthorized'"""


class NoSession(OpenSubtitlesError, AuthenticationError):
    """Exception raised when status is '406 No session'"""


class DownloadLimitReached(OpenSubtitlesError, DownloadLimitExceeded):
    """Exception raised when status is '407 Download limit reached'"""


class InvalidImdbid(OpenSubtitlesError):
    """Exception raised when status is '413 Invalid ImdbID'"""


class UnknownUserAgent(OpenSubtitlesError, AuthenticationError):
    """Exception raised when status is '414 Unknown User Agent'"""


class DisabledUserAgent(OpenSubtitlesError, AuthenticationError):
    """Exception raised when status is '415 Disabled user agent'"""


class ServiceUnavailable(OpenSubtitlesError):
    """Exception raised when status is '503 Service Unavailable'"""


def checked(response):
    """Check a response status before returning it

    :param response: a response from a XMLRPC call to OpenSubtitles
    :return: the response
    :raise: :class:`OpenSubtitlesError`

    """
    status_code = int(response['status'][:3])
    if status_code == 401:
        raise Unauthorized
    if status_code == 406:
        raise NoSession
    if status_code == 407:
        raise DownloadLimitReached
    if status_code == 413:
        raise InvalidImdbid
    if status_code == 414:
        raise UnknownUserAgent
    if status_code == 415:
        raise DisabledUserAgent
    if status_code == 503:
        raise ServiceUnavailable
    if status_code != 200:
        raise OpenSubtitlesError(response['status'])
    return response

