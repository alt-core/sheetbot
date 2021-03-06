# coding: utf-8
import logging

from google.appengine.api import taskqueue, memcache

from bottle import request, response, Bottle, abort

import main
import utility
import users
import auth


app = Bottle()


def abort_json(code, msg):
    abort(code, utility.make_error_json(code, msg))


@app.post('/api/build/<bot_name>')
def api_build(bot_name):
    bot = main.get_bot(bot_name)
    if not bot:
        abort_json(404, u'not found')

    options = {}
    options['skip_image'] = (request.params.get('skip_image') == 'true')
    options['force'] = (request.params.get('force') == 'true')

    version = main.get_options().get('scenario_version', 1)

    logging.info("start building...: options: {}, version: {}".format(options, version))

    ok, err = bot.build_scenario(options=options, version=version)

    response.content_type = 'text/plain; charset=UTF-8'
    response.headers['Access-Control-Allow-Origin'] = '*'
    if ok:
        # リロードに成功した
        return utility.make_ok_json(u"反映作業に成功しました。")
    else:
        return utility.make_ng_json(u"反映作業に失敗しました。\n\n" + err)


@app.get('/api/build_async/<bot_name>')
@app.post('/api/build_async/<bot_name>')
def api_build_async(bot_name):
    bot = main.get_bot(bot_name)
    if not bot:
        abort_json(404, u'not found')

    options = {}
    skip_option = request.params.get('skip_image')
    if skip_option:
        options['skip_image'] = skip_option
    force_option = request.params.get('force')
    if force_option:
        options['force'] = force_option

    task = taskqueue.add(url='/api/build/' + bot.name,
                         params=options,
                         retry_options=taskqueue.TaskRetryOptions(task_retry_limit=0))
    logging.info("enqueue a build task: {}, options: {}, ETA {}".format(task.name, options, task.eta))

    response.content_type = 'text/plain; charset=UTF-8'
    response.headers['Access-Control-Allow-Origin'] = '*'
    return utility.make_ok_json(u"OK")


@app.get('/api/last_build_result/<bot_name>')
def api_get_last_build_result(bot_name):
    bot = main.get_bot(bot_name)
    if not bot:
        abort_json(404, u'not found')

    result = memcache.get('last_build_result:' + bot.name)
    if result is None:
        result = u"\tNot Found"

    response.content_type = 'text/plain; charset=UTF-8'
    return result


def _do_action_iter(result, bot, user, action, attrs, level=0):
    if level > 20:
        logging.warning(u'group infinite loop: {} {}'.format(user, action))
        abort_json(400, u'infinite loop is detected')

    if user.service_name == 'group':
        for member in users.get_group_members(user.user_id):
            _do_action_iter(result, bot, member, action, attrs, level+1)
            # TODO: rate limit があるサービスでの対応
    else:
        interface = bot.get_interface(user.service_name)
        if interface is None:
            abort_json(404, u'not found')
        context = interface.create_context(user, action, attrs)
        result.append(unicode(bot.handle_action(context)))


@app.post('/api/v1/bots/<bot_name>/action')
@app.get('/api/v1/bots/<bot_name>/action')
def do_action(bot_name):
    response.content_type = 'text/plain; charset=UTF-8'

    bot = main.get_bot(bot_name)
    if not bot:
        abort_json(404, u'not found')

    user_str = request.params.getunicode('user')
    action, attrs = utility.decode_action_string(request.params.getunicode('action'))
    token = request.params.getunicode('token')

    logging.info(u"API call: bot_name: {}, user: {}, action: {}".format(bot_name, user_str, action))

    # token チェック
    if not auth.check_token(token):
        abort_json(401, u'invalid token')

    user = None
    if user_str:
        user = users.User.deserialize(user_str)
    if user is None or action is None:
        abort_json(400, u'invalid parameter')

    bot.check_reload()

    result = []
    _do_action_iter(result, bot, user, action, attrs)

    return utility.make_ok_json(u"\n".join(result))


@app.get('/_ah/start')
def start_handler():
    response.content_type = 'text/plain; charset=UTF-8'
    return u'Start successful'


@app.get('/_ah/stop')
def stop_handler():
    response.content_type = 'text/plain; charset=UTF-8'
    return u'Stop successful'


@app.get('/_ah/warmup')
def warmup_handler():
    for bot_name, bot in main.get_bots().items():
        bot.check_reload()
    response.content_type = 'text/plain; charset=UTF-8'
    return u'Warmup successful'


if __name__ == "__main__":
    app.run(host='localhost', port=8080, debug=True)
