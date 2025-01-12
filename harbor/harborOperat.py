#!/usr/bin/python3
# -*- coding: utf-8 -*-
# @Time    : 2019/9/5 上午9:01
# @Author  : Xie Chuyu
# @File    : harborOperat.py
# @Software: PyCharm
import requests
import urllib3
import json
import docker
from config import config


class Harbor(object):
    urllib3.disable_warnings()
    session = requests.session()
    base_url = ('https://' if config['harbor_tls'] else 'http://') + config['harbor_url'] + '/api/'
    client = docker.from_env()
    json_headers = {'Content-Type': 'application/json'}

    def __init__(self):
        self.client.login(username=config['harbor_username'],
                          password=config['harbor_password'],
                          registry=config['harbor_url'])

    def login_harbor(self):
        print('trying to login harbor')
        login_url = self.base_url.replace('/api', '') + 'c/login'
        data = {
            'principal': config['harbor_username'],
            'password': config['harbor_password'],
        }
        res = self.session.post(url=login_url, data=data, verify=False,
                                headers={"Content-Type": "application/x-www-form-urlencoded"})

        assert 200 <= res.status_code < 300, 'login failed, please check the harbor config'
        print('login success')
        return

    def _check_project(self, project_name_str):
        """
        check if project exist,return bool

        :param project_name_str:
        :return:
        """
        check_project_url = self.base_url + "projects?project_name=" + project_name_str
        res = self.session.head(check_project_url, verify=False)
        if res.status_code == 200:
            return True
        return False

    def _pre_push(self, project_name_str):
        """
        before push a docker, should make sure project is exist

        :param project_name_str:
        :return:
        """
        if "/" in project_name_str:
            project_name_str = project_name_str.split("/")[0]

        # if project is exist ,pass it
        if self._check_project(project_name_str):
            return

        print('trying to create project ' + project_name_str)
        create_project_url = self.base_url + "projects"
        data = json.dumps({
            "project_name": project_name_str,
            "metadata": {
                "public": "true"
            }
        })
        res = self._post_with_auth(create_project_url, data=data)

        assert 300 > res.status_code >= 200, 'create project failed ' + str(res.status_code)
        print('create project {0} success'.format(project_name_str))

    def pre_push(self, name_str):
        """
        push image to harbor

        :param name_str:
        :return:
        """

        print("pushing " + name_str)
        # make sure project is exist
        project_name = self._name_format(name_str)
        self._pre_push(project_name)
        return config['harbor_url'] + "/" + project_name

    def _name_format(self, name_str):
        name_split, project_name = name_str.split("/"), name_str
        if '.' in name_split[0]:
            with open("out/domain.txt", "a") as file:
                file.write(name_split[0])
            project_name = "/".join(name_split[1:])
            name_split = project_name.split("/")
        if len(name_split) is 1:
            project_name = 'library/' + name_split[0]
        return project_name

    def _get_with_auth(self, url):
        """
        make sure get request has auth

        :param url:
        :return:
        """

        response = self.session.get(url, verify=False, headers=self.json_headers)
        if response.status_code == 401:
            self.login_harbor()
            return self._get_with_auth(url)
        return response

    def _post_with_auth(self, url, data=None):
        """
        make sure post request has auth

        :param url:
        :return:
        """

        response = self.session.post(url, verify=False, headers=self.json_headers, data=data)
        if response.status_code == 401:
            self.login_harbor()
            return self._post_with_auth(url, data=data)
        return response

    def _delete_with_auth(self, url):
        """
                make sure get request has auth

                :param url:
                :return:
                """

        response = self.session.delete(url, verify=False, headers=self.json_headers)
        if response.status_code == 401:
            self.login_harbor()
            return self._get_with_auth(url)
        return response

    def mv_image(self, origin_name_str, target_name_str):
        """
        move a image from a project to another project or just rename it

        :param origin_name_str:
        :param target_name_str:
        :return:
        """

        print("move {0} to {1}".format(origin_name_str, target_name_str))
        image = self.client.images.pull(config['harbor_url'] + "/" + origin_name_str)
        if not image:
            return
        else:
            image = image[0]
        image_name = self.pre_push(target_name_str)
        image.tag(image_name)
        self.client.images.push(image_name)

        if ':' in origin_name_str:
            repository_name, tag = origin_name_str.split(':')[0], origin_name_str.split(':')[1]
        else:
            repository_name, tag = origin_name_str, 'latest'
        delete_url = "{0}repositories/{1}/tags/{2}".format(self.base_url, repository_name, tag)
        res = self._delete_with_auth(delete_url)
        assert res.status_code is 200, 'delete {} failed'.format(origin_name_str)
        print('move {} to {} success'.format(origin_name_str, target_name_str))

    def decorticate(self, project_name_str):
        """
        make wrong name right, for exp, /library/project/name => /project/name

        :return:
        """

        project_url = "{0}projects?name={1}".format(self.base_url, project_name_str)
        projects_response = self._get_with_auth(project_url)
        projects, project_id = projects_response.json(encoding='utf-8'), 0
        assert projects, 'project is not exist'
        if len(projects) is 1:
            project_id = projects[0]['project_id']
        else:
            for project in projects:
                if project['name'] == project_name_str:
                    project_id = project['project_id']
        assert project_id, 'project is not exist'

        repositories_url = "{0}repositories?project_id={1}".format(self.base_url, project_id)
        repositories_response = self._get_with_auth(repositories_url)
        repositories = repositories_response.json(encoding='utf-8')
        wait_to_decorticate = [x['name'] for x in repositories if len(x['name'].split('/')) > 2]

        print(wait_to_decorticate)
        for x in wait_to_decorticate:
            target = '/'.join(x.split('/')[-2:])
            try:
                self.mv_image(x, target)
            except Exception as e:
                print(e)

    def check_image(self, line):
        """
        check if this image exist in harbor

        :param line:
        :return:
        """

        project_name = self._name_format(line)
        if ':' in project_name:
            repository_name, tag = project_name.split(':')[0], project_name.split(':')[1]
        else:
            repository_name, tag = project_name, 'latest'
        registry_url = "{0}repositories/{1}/tags/{2}".format(self.base_url, repository_name, tag)
        res = self._get_with_auth(registry_url)
        if res.status_code is 200:
            return True
        else:
            return False


harbor = None


def get_harbor():
    global harbor
    if not harbor:
        harbor = Harbor()
    return harbor


if __name__ == '__main__':
    harbor = Harbor()
    harbor.login_harbor()
    # harbor.decorticate('kibana')
