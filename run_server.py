#!/usr/bin/env python3
"""A simple webservice to wrap OpeNER services.

"""
from functools import lru_cache
from typing import Iterable
from typing import Text
from typing import Tuple
from urllib.parse import urlparse

from aiohttp import ClientError
from aiohttp import ClientSession
from asyncio_extras import async_contextmanager
from sanic import Sanic
from sanic.exceptions import InvalidUsage
from sanic.exceptions import ServerError
from sanic.request import Request
from sanic.response import HTTPResponse
from sanic.response import json
from sanic.response import text


app = Sanic(__name__)


@app.route('/ping/', methods=['GET'])
async def ping(request: Request) -> HTTPResponse:
    return text('OK')


@app.route('/status/', methods=['GET'])
async def status(request: Request) -> HTTPResponse:
    urls = {key: value for key, value in app.config.items()
            if key.startswith('OPENER_') and key.endswith('_URL')}

    return json({
        'config': {
            'urls': urls
        }
    })


@app.route('/opener/', methods=['POST'])
async def opener(request: Request) -> HTTPResponse:
    nlp, steps = _parse_request(request)
    for endpoint in _build_opener_urls(steps):
        nlp = await _call_opener_service(endpoint, nlp)
    return HTTPResponse(nlp, content_type='application/xml')


def _parse_request(request: Request) -> Tuple[Text, Iterable[Text]]:
    nlp = (request.json or {}).get('text')
    if not nlp:
        raise InvalidUsage('no input defined to process, please '
                           'specify "text" request property')
    steps = (request.json or {}).get('steps')
    if not steps:
        raise InvalidUsage('no steps specified for nlp processing, '
                           'please specify at least one step, all '
                           'steps are: {}'.format(', '.join(_all_steps())))
    return nlp, steps


@lru_cache(maxsize=1)
def _get_client_cache():
    return {}


@async_contextmanager
async def _get_client_session(url: Text) -> ClientSession:
    netloc = urlparse(url).netloc

    if not netloc:
        client = ClientSession()
        yield client
        await client.close()
    else:
        cache = _get_client_cache()
        try:
            client = cache[netloc]
        except KeyError:
            client = ClientSession()
            cache[netloc] = client
        yield client


def _build_opener_urls(steps: Iterable[Text]) -> Iterable[Text]:
    try:
        return [app.config['OPENER_{}_URL'.format(step).upper()]
                for step in steps]
    except KeyError as ex:
        raise InvalidUsage('unknown step {}, all steps are: {}'
                           .format(ex, ', '.join(_all_steps())))


def _all_steps():
    return (key[len('OPENER_'):-len('_URL')] for key in app.config
            if key.startswith('OPENER_') and key.endswith('_URL'))


async def _call_opener_service(endpoint: Text, data: Text) -> Text:
    async with _get_client_session(endpoint) as session:
        async with session.post(endpoint, data={'input': data}) as response:
            try:
                response.raise_for_status()
            except ClientError as ex:
                raise ServerError('unable to call {} {}'.format(endpoint, ex))

            xml = await response.text()
            return xml


if __name__ == '__main__':
    from argparse import ArgumentParser
    from multiprocessing import cpu_count

    parser = ArgumentParser(description=__doc__)
    parser.add_argument('--host', default='0.0.0.0')
    parser.add_argument('--port', type=int, default=80)
    args = parser.parse_args()

    app.run(host=args.host, port=args.port, workers=cpu_count())
