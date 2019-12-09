import re
from datetime import datetime
from urllib.parse import unquote

from sanic import Blueprint, response
from sanic.log import logger
from sanic.response import HTTPResponse, redirect, text
from sanic_oauth.providers import GithubClient
from werkzeug.contrib.atom import AtomFeed

import config
from config import OWNER, SITE_TITLE
from ext import mako
from models.blog import MC_KEY_FEED, MC_KEY_SEARCH, Post
from models.mc import cache
from models.user import create_github_user

bp = Blueprint('index', url_prefix='/')
CODE_RE = re.compile('```([A-Za-z]+\n)?|#+')


@bp.route(config.OAUTH_REDIRECT_PATH)
@bp.route(config.OAUTH_REDIRECT_PATH + '/post/<post_id>')
async def oauth(request, post_id=None):
    if post_id is None:
        url = '/'
    else:
        url = request.app.url_for('blog.post', ident=post_id)

    if (user := request['session'].get('user')):
        return redirect(url)

    client = GithubClient(
        request.app.async_session,
        client_id=config.CLIENT_ID,
        client_secret=config.CLIENT_SECRET
    )
    if 'error' in request.args:
        return text(request.args.get('error'))

    redirect_uri = config.REDIRECT_URI
    if post_id is not None:
        redirect_uri += f'/post/{post_id}'

    if 'code' not in request.args:
        return redirect(unquote(unquote(client.get_authorize_url(
            scope='email profile', redirect_uri=redirect_uri
        ))))

    token, data = await client.get_access_token(
        request.args.get('code'),
        redirect_uri=redirect_uri
    )

    client = GithubClient(
        request.app.async_session,
        client_id=config.CLIENT_ID,
        client_secret=config.CLIENT_SECRET,
        access_token=token
    )

    try:
        user, info = await client.user_info()
    except Exception as exc:
        logger.exception(exc)
        return redirect(config.OAUTH_REDIRECT_PATH)

    user = await create_github_user(user)
    request['session']['user'] = user.to_dict()

    return redirect(url)


@cache(MC_KEY_FEED)
async def _feed(request):
    feed = AtomFeed(title=SITE_TITLE, updated=datetime.now(),
                    feed_url=request.url, url=request.host)
    posts = (await Post.get_all())[:10]
    for post in posts:
        body = post.html_content
        summary = post.excerpt

        feed.add(
            post.title, body, content_type='html', summary=summary,
            summary_type='html', author=OWNER, url=post.url,
            id=post.id, updated=post.created_at, published=post.created_at
        )
    return feed.to_string()


@bp.route('atom.xml', methods=['GET', 'HEAD'])
async def feed(request):
    return HTTPResponse(await _feed(request), status=200, headers=None,
                        content_type='text/xml')


@bp.route('/search')
@mako.template('search.html')
async def search(request):
    q = request.args.get('q') or ''
    return {'q': q}


@cache(MC_KEY_SEARCH)
async def _search_json(request):
    posts = await Post.get_all()
    return [{
        'url': post.url,
        'title': post.title,
        'content': CODE_RE.sub('', c) if (c := post.content) else ''
    } for post in posts]


@bp.route('/search.json')
async def search_json(request):
    return response.json(await _search_json(request))
