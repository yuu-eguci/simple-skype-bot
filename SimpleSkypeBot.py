# coding: utf-8

'''SimpleSkypeBot

最小構成のSkypeBotセット。
WatchDogクラスがSkypeのDBを監視して更新があったらSimpleSkypeBotを呼び出す。
SimpleSkypeBotクラスは発言の内容を調べて対応した内容をSkypeへ送る。

========================================
バージョン1.0(2016-09-09)
    完成。
バージョン1.1(2017-09-26)
    久しぶりに開いてdocとか書いた。
    macでも使えることを確認。
    なんか反応が遅いときがあるけど、ブラッシュアップはまたやる気があるときにでも。
'''

import sqlite3
import requests
import random
import time
from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer


# ==============================
# 設定
# ==============================

# keyを含む発言に反応しvalueを返す。
conf_pattern = {
    'how are you': 'BOT: so fine.',
    'who are you': 'BOT: i am bot.',
    'hello'      : 'BOT: hi.',
    'bye'        : 'BOT: take care.',
}

# skype for windowsのDBがあるディレクトリのパス
#     windowsでは C:/Users/username/AppData/Roaming/Skype/skypeId
#     macでは /Users/username/Library/Application Support/Skype/skypeId
conf_dbDirPath = '/Users/y-eguchi/Library/Application Support/Skype/y.egucchan'

# skype for web httpの送信先。httpヘッダを調べて書いてね。
conf_url = 'https://client-s.gateway.messenger.live.com/v1/users/ME/conversations/8:miroriiro/messages'

# http用のトークン。httpヘッダを同上。
conf_token = 'registrationToken=U2lnbmF0dXJlOjI6Mjg6QVFRQUFBRHplK0ZNSHlxWEx0dGRBaFhCazhFbztWZXJzaW9uOjY6MToxO0lzc3VlVGltZTo0OjE5OjUyNDgxMDU4ODg5MDI5NzAxMzY7RXAuSWRUeXBlOjc6MToxO0VwLklkOjI6Mzg6Y2lkLSgtNzY4MzAzMDI3NjM2MDQ4MjY3OClAb3V0bG9vay5jb207RXAuRXBpZDo1OjM2OmQ4ODUwODc1LTNjZGItNDcwMS1iYjY0LWEwOTU5NmQ4ODE1ZDtFcC5Mb2dpblRpbWU6NzoxOjA7RXAuQXV0aFRpbWU6NDoxOTo1MjQ4MTA1ODg4ODg2NDA4MjIzO0VwLkF1dGhUeXBlOjc6MjoxNTtFcC5FeHBUaW1lOjQ6MTk6NTI0ODEwNjc1MjgyNzM4NzkwNDtVc3IuTmV0TWFzazoxMToxOjM7VXNyLlhmckNudDo2OjE6MDtVc3IuUmRyY3RGbGc6MjowOjtVc3IuRXhwSWQ6OToxOjA7VXNyLkV4cElkTGFzdExvZzo0OjE6MDtVc2VyLkF0aEN0eHQ6Mjo0MjA6Q2xOcmVYQmxWRzlyWlc0bVkybGtMU2d0TnpZNE16QXpNREkzTmpNMk1EUTRNalkzT0NsQWIzVjBiRzl2YXk1amIyMEJBMVZwWXhReEx6RXZNREF3TVNBeE1qb3dNRG93TUNCQlRReE9iM1JUY0dWamFXWnBaV1NLVVBhS3EyUmdsUUFBQUFBQUFFQUFBQUFBQUFBQUFBQUFBQUFBQUFBQUFBQUtlUzVsWjNWalkyaGhiZ0FBQUFBQUFBQUFBQWRPYjFOamIzSmxBQUFBQUFRQUFBQUFBQUFBQUFBQUFJcFE5b3FyWkdDVkFBQUFBQUFBQUFBQUFBQUFBQUFBQUFBQkNua3VaV2QxWTJOb1lXNEFBQUFBQUFFQUFBQUlBQUFBQTFWcFl3aEpaR1Z1ZEdsMGVRNUpaR1Z1ZEdsMGVWVndaR0YwWlFoRGIyNTBZV04wY3c1RGIyNTBZV04wYzFWd1pHRjBaUWhEYjIxdFpYSmpaUTFEYjIxdGRXNXBZMkYwYVc5dUZVTnZiVzExYm1sallYUnBiMjVTWldGa1QyNXNlUT09Ow=='

# ==============================
# 設定ここまで
# ==============================

# session
session = requests.session()
session.post(conf_url)
# BOT起動時のタイムスタンプ
startTimestamp = round(time.time())
# 反応済みIDが入るリスト
doneIdList = []
# skype for webへ送るリクエストヘッダ。
headers = {
    'Accept'            :'application/json, text/javascript',
    'Accept-Encoding'   :'gzip, deflate',
    'Accept-Language'   :'ja,en-US;q=0.8,en;q=0.6',
    'BehaviorOverride'  :'redirectAs404',
    'Cache-Control'     :'no-cache, no-store, must-revalidate',
    'ClientInfo'        :('os=Windows; osVer=7; proc=Win32; lcid=en-us;'
            + ' deviceType=1; country=n/a; clientName=skype.com;'
            + ' clientVer=908/1.42.0.98//skype.com'),
    'Connection'        :'keep-alive',
    'ContextId'         :'tcid=146372019467711519',
    'Content-Type'      :'application/json',
    'Expires'           :'0',
    'Host'              :'client-s.gateway.messenger.live.com',
    'Origin'            :'https://web.skype.com',
    'Pragma'            :'no-cache',
    'Referer'           :'https://web.skype.com/ja/',
    'User-Agent'        :('Mozilla/5.0 (Windows NT 6.1)'
            + ' AppleWebKit/537.36 (KHTML, like Gecko)'
            + ' Chrome/50.0.2661.102 Safari/537.36'),
    'RegistrationToken' :conf_token,
}

class SimpleSkypeBot:
    '''main.dbから発言の内容を取得し、対応する内容をSkypeへ送る。'''

    def main(self):
        '''トップレベルメソッド。'''
        # たまにsqlite3.OperationalError: disk I/O errorが出るので
        # そんときは処理をやり直すためのtry,except。たぶん邪道。
        while True:
            try:
                recordList = self.selectRecordList()
                break
            except sqlite3.OperationalError:
                print('sqlite3.OperationalErrorが出たヨ。')
                continue
        if not recordList:
            return False
        for record in recordList:
            # 発言の内容によって返答を作る。
            reply = self.getReply(record['body_xml'])
            if not reply:
                return
            # 反応済みリストにidを追加する。
            doneIdList.append(record['id'])
            # 返答をスカイプへ送信する。
            self.sendSkype(reply)
        return

    def selectRecordList(self):
        '''main.dbからレコードを取得する。'''
        # connectionをグローバルで作るとマルチスレッドエラーになっちゃうのでここで作る。
        connection = sqlite3.connect(conf_dbDirPath + '/main.db')
        cursor = connection.cursor()
        # SQLの「body_xmlにconf_patternの内容を含む」部分を作る。
        # AND (1=0 OR `body_xml` LIKE '%key%' OR `body_xml` LIKE '%key%')こんな感じの。
        likePart = ''
        if conf_pattern:
            likePart = 'AND (1=0 '
            for key in conf_pattern:
                likePart += 'OR `body_xml` LIKE \'%%%s%%\' ' % key
            likePart = likePart + ')'
        # SQLの「反応済みリストのIDを除く」部分を作る。AND `id` NOT IN (**,**)こんな感じの。
        idPart = ''
        if doneIdList:
            idPart = 'AND `id` NOT IN ('
            for doneId in doneIdList:
                idPart += str(doneId) + ','
            idPart = idPart[0:-1] + ')'
        # 発言を取得するSQL。
        # 「BOT起動時のタイムスタンプ後」「body_xmlにconf_patternの内容を含む」「反応済みリストのIDを除く」というSQL。
        sql = ('SELECT id,body_xml FROM `Messages` '
            + 'WHERE `timestamp`>? %s %s' % (likePart, idPart))
        bind = (startTimestamp,)
        # 取得する。
        cursor.execute(sql, bind)
        trash = cursor.fetchall()
        # コネクション閉じる。
        connection.close()
        # 成形して返す。
        if not trash:
            return False
        else:
            return self.assoc(trash, ['id', 'body_xml'])

    def assoc(self, trash, columns):
        '''いつものsqlite3モジュール補助。
        [[1,A][2,B]]ってなってるのを{{id:1,name:A},{id:2,name:B}}ってディクショナリにする。'''
        rows = []
        for i in range(len(trash)):
            rows.append({})
            for j in range(len(trash[i])):
                rows[i][columns[j]] = trash[i][j]
        return rows

    def getReply(self, body_xml):
        '''body_xmlの内容に従って返答を返す。'''
        for key,value in conf_pattern.items():
            if key in body_xml:
                return value
        return False

    def sendSkype(self, reply):
        '''skype for webに送信する。'''
        postjson = ('{' +
            'content        : "%s",' % reply +
            'clientmessageid: "%s",' % random.randint(1000000000000, 9999999999999) +
            'messagetype    : "RichText",' +
            'contenttype    : "text",' +
        '}')
        session.post(conf_url, data=postjson, headers=headers)
        return True

class WatchDog(FileSystemEventHandler):
    '''ファイルの変更を感知したらSkypeBotオブジェクトのmainメソッドを走らせる。'''
    def on_modified(self, events):
        '''ファイルに変更(スカイプに発言)があったらSkypeBotオブジェクトの動作開始。'''
        if events.src_path.endswith('main.db'):
            bot.main()
            return

if __name__ in '__main__':
    bot = SimpleSkypeBot()
    dog = WatchDog()
    observer = Observer()
    observer.schedule(dog, conf_dbDirPath, recursive=True)
    observer.start()
    observer.join()
