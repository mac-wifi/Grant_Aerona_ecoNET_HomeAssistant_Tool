BRIEF
-----
Our holiday home runs off a Grant Aerona heat pump system (instructions - Reference/grant-aerona-smart-controller-installer-and-operating-instructions-uk-doc-0203-rev-20-october-2024.pdf). 

I want to monitor and control it via a Home Assistant server I have onsite. The Home Assistant server can talk to the Grant controller via an econet integration. 

This tool should run from the Home Assistant server but advise me on whether it should be a Home Assistant integration, standalone python app, or something else.

This project should be stored in Github for version control and potentially sharing later.


FUNCTIONALITY
-------------
* read system settings once a day
* read temperature and performance settings every 5 minutes
* Store all readings indefinitely
* Create a notification via Home Assistant app and email that a system or temperature setting has been changed.
    - exclude notices for any settings changes made by this tool.
* Provide one button restoration of system settings
* For the following settings provide a UI that both displays the current value and allows a new value to be set/entered. It could be a Homa Assistant UI or maybe an HTML page I can give my wife access to. By typing a number in and clicking away or pressing plus/minus buttons located to the side:
    - circuit 1 temperature
    - DHW temperature
* Method for Amazon Alexa routines to be used to change settings.
    - Ability to tell Alexa a check out date of the guests and this passes the value to Home Assistant to store in a variable, which come that date at 10am this tool will reset any changed settings to a saved configuration.
* Graph temperature and performance settings in an HTML page.
* Set a desired temperature for Circuit 1 Day, monitor the actual Circuit 1 Day setting, and revert the setting to the desired temperature when a change in temperature is detected.
* Create urgent message via SMS provider or Whatapp integration if the guest change certain types of setting, so that I am woken in the night by my iPhone.


DETAIL
------
* When building the UI the heating settings can be split into 3 categories, System, Temperature & Performance.
** Example of system settings: Heating schedule
** Example of temperature settings: circuit 1 thermostat,DHW temperature
** Example of performance settings: Flow rate,Return rate

* Internal econet IP - 192.168.1.6
* External econet address - http://theviewmoelfre.duckdns.org:8123 (not currently available externally but can be enabled if there is a good reason or for testing)
* Internal Home Assistant IP - 192.168.1.3
* External Home Assistant address - https://tulbefewrh4tx7ksscieb4qumekmbgsx.ui.nabu.casa/


REFERENCE
---------

* These files show the output of some of the API commands. The API command to create each file is:
** http://econet_local_ip/econet/editParams - Reference/editParams_Output.json
** http://econet_local_ip/econet/regParams - Reference/regParams_Output.json
** http://econet_local_ip/econet/sysParams - Reference/sysParams_Output.json

* Another developer has already started this work for Econet but for different hardware which does not match mine and therefore does not expose all the settings I want. Its github repo is here and we can utilise any existing knowledge or code that is helpful - https://github.com/jontofront/ecoNET-300-Home-Assistant-Integration


TESTING
-------
* I can create a local virtual home assistant server for deploying the app too while testing. 
* Testing will have to be conducted using the live Econet system via an external IP, so testing must be cautious and not able to break anything on the live system. Some sort of break point where every API command to be sent to the live econet system is manually inspected by me before being approved to send.
* To identify what all of the settings mean in the API output I suggest I provide a before and after API extract for every setting I change in the vendors own iOS app so the you can identify the parameter that was changed by the setting. This will be a slow repetitive process but I can't think of another way.