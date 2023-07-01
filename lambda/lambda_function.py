# -*- coding: utf-8 -*-

# This sample demonstrates handling intents from an Alexa skill using the Alexa Skills Kit SDK for Python.
# Please visit https://alexa.design/cookbook for additional examples on implementing slots, dialog management,
# session persistence, api calls, and more.
# This sample is built using the handler classes approach in skill builder.

import logging
import ask_sdk_core.utils as ask_utils

from ask_sdk_core.skill_builder import SkillBuilder
from ask_sdk_core.dispatch_components import AbstractRequestHandler
from ask_sdk_core.dispatch_components import AbstractExceptionHandler
from ask_sdk_core.handler_input import HandlerInput

from ask_sdk_model import Response

from ask_sdk_core.utils import get_supported_interfaces
from ask_sdk_model.interfaces.alexa.presentation.apl import RenderDocumentDirective

import requests
import os
import boto3
import json

from ask_sdk_dynamodb.adapter import DynamoDbAdapter
from ask_sdk_core.dispatch_components import AbstractRequestInterceptor
from ask_sdk_core.dispatch_components import AbstractResponseInterceptor

from ask_sdk_core.skill_builder import CustomSkillBuilder
from ask_sdk_dynamodb.adapter import DynamoDbAdapter

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# You can get these values from Skill Dashboard > Tools > Permissions > Alexa Skill Messaging section. 
ALEXACLIENTID = "amzn1.application-oa2-client.aefa2ff2b13841a48c7fd53dee1d488b"
ALEXACLIENTSECRET = "amzn1.oa2-cs.v1.c60552d52f32ad4e784c21b2b401116de92aeb25b02903e57f1d987caa363672"

ddb_region = os.environ.get('DYNAMODB_PERSISTENCE_REGION')
ddb_table_name = os.environ.get('DYNAMODB_PERSISTENCE_TABLE_NAME')

ddb_resource = boto3.resource('dynamodb', region_name=ddb_region)
dynamodb_adapter = DynamoDbAdapter(table_name=ddb_table_name, create_table=False, dynamodb_resource=ddb_resource)


launchDocument = './documents/launch_template.json'
plantCareDocument = './documents/plant_care.json'
datasourceDocument = './documents/datasource.json'

def _load_apl_document(file_path):
    # type: (str) -> Dict[str, Any]
    """Load the apl json document at the path into a dict object."""
    with open(file_path) as f:
        return json.load(f)

def getAccessToken():
    TOKEN_URI = "https://api.amazon.com/auth/o2/token"

    token_params = {
        "grant_type" : "client_credentials",
        "scope": "alexa::datastore",
        "client_id": ALEXACLIENTID,
        "client_secret": ALEXACLIENTSECRET
    }
    token_headers = {
        "Content-Type": "application/json",
        "charset":"UTF-8"
    }
    
    response = requests.post(TOKEN_URI, headers=token_headers, data=json.dumps(token_params), allow_redirects=True)

    if response.status_code != 200:
        logger.info("Error requesting token")
        return None

    return response.text

"""
 * UsagesRemoved triggers when a user removes your widget package on their device.  
"""
class RemoveWidgetRequestHandler(AbstractRequestHandler):
    # The skill receives the UsagesRemoved when a user removes your widget from a device (and Alexa uninstalls the package)
    def can_handle(self, handler_input):
        # type: (HandlerInput) -> bool
        return ask_utils.is_request_type("Alexa.DataStore.PackageManager.UsagesRemoved")(handler_input)

    def handle(self, handler_input):
        # type: (HandlerInput) -> Response
        instanceId = handler_input.request_envelope.request.payload.usages[0].instance_id
        attributes = handler_input.attributes_manager.persistent_attributes or {}
        logger.info("##### The widget has been removed")
            
        if "instances" in attributes:    
            # remove all instanceID from list
            attributes["instances"] = list(filter((instanceId).__ne__, attributes["instances"]))
            
            handler_input.attributes_manager.persistent_attributes = attributes
            handler_input.attributes_manager.save_persistent_attributes()
            
        speak_output ="Remove Widget Requested"
        ask_output ="Widget removed. What would you like to do now"
        return (
            handler_input.response_builder
                .speak(speak_output)
                .ask(ask_output)
                .response
        )

class InstallWidgetRequestHandler(AbstractRequestHandler):
    # The skill receives the UsagesInstalled request when Alexa installs your widget on a user's device
    def can_handle(self, handler_input):
        # type: (HandlerInput) -> bool
        return ask_utils.is_request_type("Alexa.DataStore.PackageManager.UsagesInstalled")(handler_input)

    def handle(self, handler_input):
        # type: (HandlerInput) -> Response

        logger.info("###### The widget has been installed")
        attributes = handler_input.attributes_manager.persistent_attributes

        commands = [
            {
                "type": "PUT_OBJECT",
                "namespace": "plantCareReminder",
                "key": "plantData",
                "content": { 
                    "lastWateredDate": attributes["date"] or ""
                }
            }
        ]

        tokenResponse = getAccessToken()
        userId = handler_input.request_envelope.context.system.user.user_id
        """
        Target all the user’s devices using type: USER, and id: userId, so that all their Plant Care widgets will receive the last watered date
        """
        target = {
            "type": "USER",
            "id": userId
        }

        # push update to DataStore service which will distribute the update to all targeted devices

        updateDatastore(tokenResponse, commands, target)

        # OPTIONAL in Alexa NodeJS example - add instanceID to list
        logger.info(handler_input.request_envelope.request.payload)
        instanceId = handler_input.request_envelope.request.payload.usages[0].instance_id
        if "instances" in attributes:
            attributes["instances"].append(instanceId)
        else:
            attributes["instances"] = [instanceId]
        handler_input.attributes_manager.persistent_attributes  = attributes
        handler_input.attributes_manager.save_persistent_attributes()
            
        speak_output ="Install Widget Requested"
        return (
            handler_input.response_builder
                .speak(speak_output)
                .ask(speak_output)
                .response
        )

"""
 * UpdateRequest triggers when a user receives an widget update on their device
"""
class UpdateWidgetRequestHandler(AbstractRequestHandler):
    # The skill receives the UpdateRequest when Alexa updates your package on a user's device with a new version and ..
    def can_handle(self, handler_input):
        # type: (HandlerInput) -> bool
        return ask_utils.is_request_type("Alexa.DataStore.PackageManager.UpdateRequest")(handler_input)

    def handle(self, handler_input):
        # type: (HandlerInput) -> Response
        # for now this information is not needed by this sample skill. 
        logger.info("Updated from Version" + handler_input.request_envelope.request.fromVersion)
        logger.info("Updated to Version" + handler_input.request_envelope.request.toVersion)

        return (
            handler_input.response_builder
                .response
        )

"""
 * InstallationError triggers notify the skill about any errors that happened during package installation, removal, or updates.
"""
class WidgetInstallationErrorHandler (AbstractRequestHandler):
    # Notify the skill about any errors that happened during widget installation, removal, or updates
    def can_handle(self, handler_input):
        # type: (HandlerInput) -> bool
        return ask_utils.is_request_type("Alexa.DataStore.PackageManager.InstallationError")(handler_input)
        
    def handle(self, handler_input):
        logger.info("handler_input.request_envelope.request_envelope.request.error")
        logger.info(handler_input.request_envelope.request.error)
        logger.info("Error Type: " + handler_input.request_envelope.request.error.type)
        speak_output ="Sorry, there was an error installing the widget. Please try again later"
        return (
            handler_input.response_builder
                .speak(speak_output)
                .response
        )

def updateDatastore(token, commands, target):
    REQUEST_URI = "https://api.eu.amazonalexa.com/v1/datastore/commands"
    json_token = json.loads(token)
    headers =  {
        "Content-Type": "application/json",
        "Authorization": "bearer {}".format(json_token["access_token"])
    }
    
    data = {
        "commands": commands,
        "target": target
    }
    
    response = requests.post(REQUEST_URI, headers = headers, data = json.dumps(data))

    if response.status_code != 200:
        logger.info("Error requesting token during update data store")
        return None

    return response.text

"""
 * Handler to process any incoming APL UserEvent that originates from a SendEvent command
 * from within the Plant Care widget or the Plant Care skill APL experience
"""
class APLEventHandler (AbstractRequestHandler):
    def can_handle(self, handler_input):
        # type: (HandlerInput) -> bool
        return ask_utils.is_request_type("Alexa.Presentation.APL.UserEvent")(handler_input)

    def handle(self, handler_input):
        logger.info("in APLEventHandler")
        eventType = handler_input.request_envelope.request.arguments[0]
        should_end_session = False 
        speak_output = ""
        logger.info(eventType)
        if eventType =='openSkill': 
            # If the user taps on header, launch the skill.
            return LaunchRequestHandler.handle(self, handler_input)
        if eventType =='plantWateredWidget': 
            # If the user taps on the button through widget, set the withShouldEndSession to true. 
            should_end_session = True
        if eventType =='plantWateredSkill': 
            # If the user taps on the button through the APL document within skill, the session is not ended and sends a speech response back. 
            speak_output = "The plant has now been watered."
            handler_input.response_builder.speak(speak_output)
        
        date = handler_input.request_envelope.request.arguments[1]
        userId = handler_input.request_envelope.context.system.user.user_id

        attributes = handler_input.attributes_manager.persistent_attributes

        attributes["date"] = date
        handler_input.attributes_manager.persistent_attributes  = attributes
        handler_input.attributes_manager.save_persistent_attributes()

        commands = [
            {
                "type": "PUT_OBJECT",
                "namespace": "plantCareReminder",
                "key": "plantData",
                "content": { 
                    "lastWateredDate": date
                }
            }
        ]
        target = {
            "type": "USER",
            "id": userId
        }

        tokenResponse = getAccessToken()
        updateDatastore(tokenResponse, commands, target)
        
        # and go to launch screen, or end session
        return (
            handler_input.response_builder
                .set_should_end_session(should_end_session)
                .add_directive(
                        RenderDocumentDirective(
                            token="pagerToken",
                            document = _load_apl_document(launchDocument),
                            datasources=_load_apl_document(datasourceDocument)
                        )
                    )
                .response
        )

class LaunchRequestHandler(AbstractRequestHandler):
    """Handler for Skill Launch."""
    def can_handle(self, handler_input):
        # type: (HandlerInput) -> bool

        return ask_utils.is_request_type("LaunchRequest")(handler_input)

    def handle(self, handler_input):
        # type: (HandlerInput) -> Response
        speak_output = "Welcome to the Plant Care Skill. You can say water my plant to water it or say help to know more. What would you like to do?"
        
        attributes = handler_input.attributes_manager.persistent_attributes 
        if 'date' not in attributes:
            attributes['date'] = ""
        handler_input.attributes_manager.persistent_attributes  = attributes
        handler_input.attributes_manager.save_persistent_attributes()
        
        if get_supported_interfaces(handler_input).alexa_presentation_apl is not None:
            return (
            handler_input.response_builder
                .ask(speak_output)
                .speak(speak_output)
                .add_directive(
                        RenderDocumentDirective(
                            token="pagerToken",
                            document = _load_apl_document(launchDocument),
                            datasources=_load_apl_document(datasourceDocument)
                        )
                    )
                .response
        )

        else:
            speak_output = "Sorry you dont have a screen to show the skill"
            return (
            handler_input.response_builder
                .speak(speak_output)
                .ask(speak_output)
                .response
        )

class PlantCareIntentHandler(AbstractRequestHandler):
    """Handler for Hello World Intent."""
    def can_handle(self, handler_input):
        # type: (HandlerInput) -> bool
        return ask_utils.is_intent_name("PlantCareIntent")(handler_input)

    def handle(self, handler_input):
        attributes = handler_input.attributes_manager.persistent_attributes
        if 'date' not in attributes:
            attributes['date'] = ""
        handler_input.attributes_manager.persistent_attributes  = attributes
        handler_input.attributes_manager.save_persistent_attributes()
        
        if get_supported_interfaces(handler_input).alexa_presentation_apl is not None:
            return (
                handler_input.response_builder
                .add_directive(RenderDocumentDirective(
                    document = _load_apl_document(plantCareDocument),
                    datasources = {
                        "alexaPhotoData": {
                            "title": "Plant Care Reminder",
                            "backgroundImage": {
                                "sources": [
                                    {
                                        "url": "https://d2o906d8ln7ui1.cloudfront.net/images/templates_v3/long_text/LongTextSampleBackground_Dark.png",
                                        "size": "large"
                                    }
                                ]
                            },
                            "lastWateredDate": attributes["date"] or "",
                            "primaryText": "Haworthia Zebra Plant",
                            "secondaryText": "Water today",
                            "buttonText": "I watered my plant"
                        }
                    }
                ))
            
                .speak('Tap on the button to water your plant.')
                .response
            )
        else:
            speak_output = "Sorry your device doesn't have a screen"
            return (
            handler_input.response_builder
                .speak(speak_output)
                .response
        )

# unwaterplant
class unwaterIntentHandler(AbstractRequestHandler):
    """Handler for Hello World Intent."""
    def can_handle(self, handler_input):
        # type: (HandlerInput) -> bool
        return ask_utils.is_intent_name("unwaterplant")(handler_input)

    def handle(self, handler_input):
        attributes = handler_input.attributes_manager.persistent_attributes
        date = ""
        attributes['date'] = date
        handler_input.attributes_manager.persistent_attributes = attributes
        handler_input.attributes_manager.save_persistent_attributes()
        
        userId = handler_input.request_envelope.context.system.user.user_id

        commands = [
            {
                "type": "PUT_OBJECT",
                "namespace": "plantCareReminder",
                "key": "plantData",
                "content": { 
                    "lastWateredDate": date
                }
            }
        ]
        target = {
            "type": "USER",
            "id": userId
        }

        tokenResponse = getAccessToken()
        updateDatastore(tokenResponse, commands, target)
        
        return (
            handler_input.response_builder
                .speak('Your plant needs watering, say water my plant')
                .ask('Your plant needs watering')
                .add_directive(
                        RenderDocumentDirective(
                            token="pagerToken",
                            document = _load_apl_document(launchDocument),
                            datasources=_load_apl_document(datasourceDocument)
                        )
                    )
                .response
        )

class HelpIntentHandler(AbstractRequestHandler):
    """Handler for Help Intent."""
    def can_handle(self, handler_input):
        # type: (HandlerInput) -> bool
        return ask_utils.is_intent_name("AMAZON.HelpIntent")(handler_input)

    def handle(self, handler_input):
        # type: (HandlerInput) -> Response
        speak_output = "You can say water my plant to water it or say help to know more"

        return (
            handler_input.response_builder
                .speak(speak_output)
                .ask(speak_output)
                .response
        )


class CancelOrStopIntentHandler(AbstractRequestHandler):
    """Single handler for Cancel and Stop Intent."""
    def can_handle(self, handler_input):
        # type: (HandlerInput) -> bool
        return (ask_utils.is_intent_name("AMAZON.CancelIntent")(handler_input) or
                ask_utils.is_intent_name("AMAZON.StopIntent")(handler_input))

    def handle(self, handler_input):
        # type: (HandlerInput) -> Response
        speak_output = "Goodbye!"

        return (
            handler_input.response_builder
                .speak(speak_output)
                .response
        )

class FallbackIntentHandler(AbstractRequestHandler):
    """Single handler for Fallback Intent."""
    def can_handle(self, handler_input):
        # type: (HandlerInput) -> bool
        return ask_utils.is_intent_name("AMAZON.FallbackIntent")(handler_input)

    def handle(self, handler_input):
        # type: (HandlerInput) -> Response
        logger.info("In FallbackIntentHandler")
        speech = "In Fallback Intent Handler, I'm not sure. You can say Hello or Help. What would you like to do?"
        reprompt = "I didn't catch that. What can I help you with?"

        return handler_input.response_builder.speak(speech).ask(reprompt).response

class SessionEndedRequestHandler(AbstractRequestHandler):
    """Handler for Session End."""
    def can_handle(self, handler_input):
        # type: (HandlerInput) -> bool
        return ask_utils.is_request_type("SessionEndedRequest")(handler_input)

    def handle(self, handler_input):
        # type: (HandlerInput) -> Response
        # Any cleanup logic goes here.

        return handler_input.response_builder.response

class IntentReflectorHandler(AbstractRequestHandler):
    """The intent reflector is used for interaction model testing and debugging.
    It will simply repeat the intent the user said. You can create custom handlers
    for your intents by defining them above, then also adding them to the request
    handler chain below.
    """
    def can_handle(self, handler_input):
        # type: (HandlerInput) -> bool
        return ask_utils.is_request_type("IntentRequest")(handler_input)

    def handle(self, handler_input):
        # type: (HandlerInput) -> Response
        intent_name = ask_utils.get_intent_name(handler_input)
        speak_output = "You just triggered " + intent_name + "."

        return (
            handler_input.response_builder
                .speak(speak_output)
                # .ask("add a reprompt if you want to keep the session open for the user to respond")
                .response
        )

class CatchAllExceptionHandler(AbstractExceptionHandler):
    """Generic error handling to capture any syntax or routing errors. If you receive an error
    stating the request handler chain is not found, you have not implemented a handler for
    the intent being invoked or included it in the skill builder below.
    """
    def can_handle(self, handler_input, exception):
        # type: (HandlerInput, Exception) -> bool
        return True

    def handle(self, handler_input, exception):
        # type: (HandlerInput, Exception) -> Response
        logger.error(exception, exc_info=True)

        speak_output = "Sorry, I had trouble doing what you asked. Please try again."

        return (
            handler_input.response_builder
                .speak(speak_output)
                .ask(speak_output)
                .response
        )

# The SkillBuilder object acts as the entry point for your skill, routing all request and response
# payloads to the handlers above. Make sure any new handlers or interceptors you've
# defined are included below. The order matters - they're processed top to bottom.

class LoadPersistenceAttributesRequestInterceptor(AbstractRequestInterceptor):
    #Check if user is invoking skill for first time and initialize preset
    def process(self, handler_input):
        # type: (HandlerInput) -> None
        #handler_input.attributes_manager.delete_persistent_attributes()
        
        persistent_attributes = handler_input.attributes_manager.persistent_attributes
        
        return

class SavePersistenceAttributesResponseInterceptor(AbstractResponseInterceptor):
    #Save persistence attributes before sending response to user.
    def process(self, handler_input, response):
        # type: (HandlerInput, Response) -> None
        
        handler_input.attributes_manager.save_persistent_attributes()
        
        return

sb = SkillBuilder()

sb = CustomSkillBuilder(persistence_adapter = dynamodb_adapter)

# Interceptors
sb.add_global_request_interceptor(LoadPersistenceAttributesRequestInterceptor())
sb.add_global_response_interceptor(SavePersistenceAttributesResponseInterceptor())

sb.add_request_handler(InstallWidgetRequestHandler())
sb.add_request_handler(RemoveWidgetRequestHandler())
sb.add_request_handler(UpdateWidgetRequestHandler())
sb.add_request_handler(WidgetInstallationErrorHandler())
sb.add_request_handler(APLEventHandler())
sb.add_request_handler(LaunchRequestHandler())
sb.add_request_handler(PlantCareIntentHandler())
sb.add_request_handler(unwaterIntentHandler())
sb.add_request_handler(HelpIntentHandler())
sb.add_request_handler(CancelOrStopIntentHandler())
sb.add_request_handler(FallbackIntentHandler())
sb.add_request_handler(SessionEndedRequestHandler())
sb.add_request_handler(IntentReflectorHandler()) # make sure IntentReflectorHandler is last so it doesn't override your custom intent handlers

sb.add_exception_handler(CatchAllExceptionHandler())

lambda_handler = sb.lambda_handler()
