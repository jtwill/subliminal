#!/usr/bin/env python
# -*- coding: utf-8 -*-
from __future__ import print_function, unicode_literals
from sympy import Eq, symbols, solve


# Symbols
release_group, resolution, format, video_codec, audio_codec = symbols('release_group resolution format video_codec audio_codec')
imdb_id, hash, title, series, tvdb_id, season, episode = symbols('imdb_id hash title series tvdb_id season episode')  # @ReservedAssignment
year = symbols('year')


def get_episode_equations():
    """Get the score equations for a :class:`~subliminal.video.Episode`

    The equations are the following:

    1. hash = resolution + format + video_codec + audio_codec + release_group + series + year + season
    2. series = resolution + video_codec + audio_codec +  release_group + format + 1
    3. year = series
    4. tvdb_id = series + year
    5. season = series 
    6. imdb_id = series + season + episode + year
    7. format = 4 
    8. resolution = 4 
    9. video_codec = 1 
    10. title = season + episode
    11. season = episode
    12. release_group = 8 
    13. audio_codec = 2

    :return: the score equations for an episode
    :rtype: list of :class:`sympy.Eq`

    """
    equations = []
    equations.append(Eq(hash, resolution + format + video_codec + audio_codec + release_group + series + year + season))
    equations.append(Eq(series, resolution + video_codec + audio_codec + release_group + format + 1))
    equations.append(Eq(series, year))
    equations.append(Eq(tvdb_id, series + year))
    equations.append(Eq(season, series))
    equations.append(Eq(imdb_id, series + season + episode + year))
    equations.append(Eq(format, 4))
    equations.append(Eq(resolution, 4))
    equations.append(Eq(video_codec, 1))
    equations.append(Eq(title, season + episode))
    equations.append(Eq(season, episode))
    equations.append(Eq(release_group, 8))
    equations.append(Eq(audio_codec, 2))
    return equations


def get_movie_equations():
    """Get the score equations for a :class:`~subliminal.video.Movie`

    The equations are the following:

    1. hash = resolution + format + video_codec + audio_codec + title + year + release_group
    2. imdb_id = hash
    3. resolution = video_codec
    4. video_codec = 2 * audio_codec
    5. format = video_codec + audio_codec
    6. title = resolution + video_codec + audio_codec + year + 1
    7. release_group = resolution + video_codec + audio_codec + 1
    8. year = release_group + 1
    9. audio_codec = 1

    :return: the score equations for a movie
    :rtype: list of :class:`sympy.Eq`

    """
    equations = []
    equations.append(Eq(hash, resolution + format + video_codec + audio_codec + title + year + release_group))
    equations.append(Eq(imdb_id, hash))
    equations.append(Eq(resolution, video_codec))
    equations.append(Eq(video_codec, 2 * audio_codec))
    equations.append(Eq(format, video_codec + audio_codec))
    equations.append(Eq(title, resolution + video_codec + audio_codec + year + 1))
    equations.append(Eq(video_codec, 2 * audio_codec))
    equations.append(Eq(release_group, resolution + video_codec + audio_codec + 1))
    equations.append(Eq(year, release_group + 1))
    equations.append(Eq(audio_codec, 1))
    return equations


if __name__ == '__main__':
    print(solve(get_episode_equations(), [release_group, resolution, format, video_codec, audio_codec, imdb_id,
                                          hash, series, tvdb_id, season, episode, title, year]))
    print(solve(get_movie_equations(), [release_group, resolution, format, video_codec, audio_codec, imdb_id,
                                        hash, title, year]))
