import os
import json
import logging
import sys
from time import sleep

import boto3
import requests
import yaml

# credentials from this aws profile will be used
os.environ["AWS_PROFILE"] = "hkpoc"
os.environ["AWS_DEFAULT_REGION"] = "us-east-1"

IAM_CWAS_LOGS_POLICY = (
    "arn:aws:iam::aws:policy/service-role/AWSAppSyncPushToCloudWatchLogs"
)
IAM_ASSUME_APPSYNC_ROLE_POLICY = json.dumps(
    {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Effect": "Allow",
                "Principal": {"Service": "appsync.amazonaws.com"},
                "Action": "sts:AssumeRole",
            }
        ],
    }
)
logger = logging.getLogger("__name__")
logger.setLevel(logging.DEBUG)
logger.addHandler(logging.StreamHandler(sys.stdout))


def log(what: str, level: int = logging.INFO):
    logger.log(level, what)
    if level > logging.WARN:
        exit(-1)


class IAMClient:
    """a client for managing iam resources"""

    def __init__(self):
        self.client = boto3.client("iam")

    def cloudwatch_log_role(self, name: str, role_policy: str, assume_role_policy: str):
        """creates a role to write cloudwatch logs"""
        role_name = f"{name}CloudWatchLogsRole"
        role = self.client.create_role(
            RoleName=role_name,
            AssumeRolePolicyDocument=assume_role_policy,
        )
        self.client.attach_role_policy(RoleName=role_name, PolicyArn=role_policy)
        return role

    def lambda_invoke_role(self, name: str, lambda_arn: str, assume_role_policy: str):
        """
        creates a role to invoke lambda function

        - first a policy is created allowing invokation of given lambda
        function
        - next a role is created and the policy is attached to it
        """
        role_name = f"{name}LambdaRole"
        policy = self.client.create_policy(
            PolicyName=f"{name}LambdaPolicy",
            PolicyDocument=json.dumps(
                {
                    "Version": "2012-10-17",
                    "Statement": [
                        {
                            "Effect": "Allow",
                            "Action": ["lambda:invokeFunction"],
                            "Resource": [
                                f"arn:aws:lambda:us-east-1:208638726313:function:{lambda_arn.split(':')[-1]}",
                                f"arn:aws:lambda:us-east-1:208638726313:function:{lambda_arn.split(':')[-1]}:*",
                            ],
                        }
                    ],
                }
            ),
        )
        role = self.client.create_role(
            RoleName=role_name,
            AssumeRolePolicyDocument=assume_role_policy,
        )
        self.client.attach_role_policy(
            RoleName=role_name, PolicyArn=policy["Policy"]["Arn"]
        )
        return role


class AppSyncClient:
    """a client for provisioning different appsync resources"""

    def __init__(self):
        self.client = boto3.client("appsync")
        self.iam = IAMClient()
        # hard-coded values are for testing without actually creating
        # aws resources repeatedly, will be removed finally
        self.api_name = "MovieLensAPI"
        self.api_id = "mseva6lrzbdhbc7n4mnxwo434e"
        self.api_key = "da2-v6mcgmqdgrdo3a5zpv2iqrpawi"
        self.uris = {
            "REALTIME": "wss://hil7af3klzhxzhiy2kxyeosfbq.appsync-realtime-api.us-east-1.amazonaws.com/graphql",
            "GRAPHQL": "https://rcvqmkujwbgjtpbb4xpv44oplu.appsync-api.us-east-1.amazonaws.com/graphql",
        }

    def create_api(self, name: str):
        """
        creates and returns an appsync api

        - first an iam role is created to allow the api to push logs to
        cloudwatch
        - next the appsync api is created
        - finally an api key is generated to allow api invokation
        """
        self.api_name = name
        # need a role for cloudwatch logs
        logs_role = self.iam.cloudwatch_log_role(
            name=name,
            role_policy=IAM_CWAS_LOGS_POLICY,
            assume_role_policy=IAM_ASSUME_APPSYNC_ROLE_POLICY,
        )
        response = self.client.create_graphql_api(
            name=name,
            logConfig={
                "fieldLogLevel": "ALL",
                "cloudWatchLogsRoleArn": logs_role["Role"]["Arn"],
                "excludeVerboseContent": True,
            },
            authenticationType="API_KEY",
        )
        if response["ResponseMetadata"]["HTTPStatusCode"] not in [200, 201]:
            log("appsync api creation failed!", logging.FATAL)
        self.api_id = response["graphqlApi"]["apiId"]
        self.uris = response["graphqlApi"]["uris"]
        # an api key must be created in order to invoke the api after creation
        key_resp = self.client.create_api_key(apiId=self.api_id)
        self.api_key = key_resp["apiKey"]["id"]
        return response

    def create_schema(self, definition: bytes):
        """initiates the creation of a graphql schema in the appsync api"""
        response = self.client.start_schema_creation(
            apiId=self.api_id, definition=definition
        )
        if response["ResponseMetadata"]["HTTPStatusCode"] not in [200, 201]:
            log("graphql schema creation NOT started!", logging.FATAL)
        return response

    def schema_created(self):
        """
        schema creation is asynchronous, we need to check the creation status
        before moving ahead
        """
        counter = 1
        while True:
            response = self.client.get_schema_creation_status(apiId=self.api_id)
            if response["ResponseMetadata"]["HTTPStatusCode"] not in [200, 201]:
                log("unable to fetch schema creation status!", logging.FATAL)
            if response["status"] in ["SUCCESS", "ACTIVE"]:
                return
            elif response["status"] in ["PROCESSING"]:
                log("graphql schema creation in progress...")
            else:
                log(
                    f"graphql schema creation {response['status']}: "
                    f"{response['details']}",
                    logging.FATAL,
                )
            sleep(counter * counter * 5)
            counter += 1
            if counter > 5:
                log("graphql schema creation timed out!", logging.FATAL)

    def create_data_source(self, name: str, lambda_arn: str):
        """
        creates a lambda data source

        - first a role is created to allow lambda invokation
        - next the data source is created
        """
        data_source_name = f"{name}DataSource"
        lambda_role = self.iam.lambda_invoke_role(
            name=data_source_name,
            lambda_arn=lambda_arn,
            assume_role_policy=IAM_ASSUME_APPSYNC_ROLE_POLICY,
        )
        response = self.client.create_data_source(
            apiId=self.api_id,
            name=data_source_name,
            type="AWS_LAMBDA",
            serviceRoleArn=lambda_role["Role"]["Arn"],
            lambdaConfig={"lambdaFunctionArn": lambda_arn},
        )
        if response["ResponseMetadata"]["HTTPStatusCode"] not in [200, 201]:
            log("data source creation failed!", logging.FATAL)
        return response

    def create_type(self, definition: str, type_format: str = "SDL") -> dict:
        """creates a new graphql schema `type`"""
        response = self.client.create_type(
            apiId=self.api_id, definition=definition, format=type_format
        )
        if response["ResponseMetadata"]["HTTPStatusCode"] not in [200, 201]:
            log("resolver creation failed!", logging.FATAL)
        return response

    def update_type(self, name: str, definition: str, type_format: str = "SDL") -> dict:
        """updates the definition of given graphql schema `type`"""
        response = self.client.update_type(
            apiId=self.api_id, typeName=name, definition=definition, format=type_format
        )
        if response["ResponseMetadata"]["HTTPStatusCode"] not in [200, 201]:
            log("resolver creation failed!", logging.FATAL)
        return response

    def create_resolver(self, type_name: str, field_name: str, data_source_name: str):
        """
        creates a resolver which defines a mapping between the given
        field of the given `type` and the
        lambda function represented by the data source
        """
        request_mapping = """{
            "version": "2017-02-28",
            "operation": "Invoke",
            "payload": $util.toJson($context.args)
        }"""
        response_mapping = """$util.toJson($context.result)"""
        response = self.client.create_resolver(
            apiId=self.api_id,
            typeName=type_name,
            fieldName=field_name,
            dataSourceName=data_source_name,
            requestMappingTemplate=request_mapping,
            responseMappingTemplate=response_mapping,
            kind="UNIT",
        )
        if response["ResponseMetadata"]["HTTPStatusCode"] not in [200, 201]:
            log("resolver creation failed!", logging.FATAL)
        return response

    def query(self, payload: str):
        """invokes a graphql query of the appsync api"""
        headers = {"x-api-key": self.api_key, "Content-Type": "application/json"}
        response = requests.request(
            "POST", self.uris["GRAPHQL"], headers=headers, data=payload
        )
        return response.text


if __name__ == "__main__":
    args = sys.argv[1:]

    if not args:
        print("yaml file is required as a parameter")
        sys.exit(1)

    log("initializing...")
    file_name = args[0]
    cfg = None
    log(f"reading {file_name}...")
    with open(file_name, "r") as yaml_file:
        cfg = yaml.safe_load(yaml_file)

    appsync_client = AppSyncClient()
    log("creating appsync api...")

    if cfg:
        create_api_resp = appsync_client.create_api(cfg["api"]["name"])
        log(f"api created, id: {appsync_client.api_id}, creating schema...")
        create_schema_resp = appsync_client.create_schema(
            str.encode(cfg["api"]["schema"])
        )
        log("graphql schema creation started...")
        appsync_client.schema_created()
        log("graphql schema created, processing types...")
        type_name = None
        for type_def in cfg["api"]["types"]:
            verbose_name = type_def["verbose_name"]
            log(f"[{verbose_name}] creating data source...")
            create_data_source_resp = appsync_client.create_data_source(
                name=f"{appsync_client.api_name}{type_def['datasource_name']}",
                lambda_arn=type_def["lambda_arn"],
            )
            log(f"[{verbose_name}] data source created, creating type...")

            # this logic is not 100%, a subsequent type overwrites an existing
            # type
            # TODO: re-write the logic to define all types
            if type_name:
                update_type_resp = appsync_client.update_type(
                    name=type_name, definition=type_def["definition"]
                )
                log(f"[{verbose_name}] type created, creating resolver...")
            else:
                create_type_resp = appsync_client.create_type(
                    definition=type_def["definition"]
                )
                type_name = create_type_resp["type"]["name"]
                log(f"[{verbose_name}] type created, creating resolver...")

            create_resolver_resp = appsync_client.create_resolver(
                type_name=type_name,
                field_name=type_def["field_name"],
                data_source_name=create_data_source_resp["dataSource"]["name"],
            )
            log(f"[{verbose_name}] resolver for similar items created...")

    # log("wait 30 seconds for propagation...")
    # sleep(30)
    # log("calling graphql query api...")
    # payload = "{\"query\":\"query MyQuery {\\r\\n  similarItems(itemId: 1000)\\r\\n}\",\"variables\":{}}"
    # result = appsync_client.query(payload)
    # log(f"response from graphql query: {json.loads(result)}...")
