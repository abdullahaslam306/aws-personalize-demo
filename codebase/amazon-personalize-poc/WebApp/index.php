<?php

function ApiCall($apiName, $query){

  $APIURL = 'https://rnqpqhzuhjam5f2ignmiecqaw4.appsync-api.us-east-1.amazonaws.com/graphql';
  $APIKEY = 'da2-tfbfskktbfgdvkdqq6uagzemcq';
  echo "<h2>$apiName</h2>";
  $curl = curl_init();

  curl_setopt_array($curl, array(
    CURLOPT_URL => $APIURL,
    CURLOPT_RETURNTRANSFER => true,
    CURLOPT_MAXREDIRS => 10,
    CURLOPT_TIMEOUT => 0,
    CURLOPT_FOLLOWLOCATION => true,
    CURLOPT_HTTP_VERSION => CURL_HTTP_VERSION_1_1,
    CURLOPT_CUSTOMREQUEST => 'POST',
    CURLOPT_POSTFIELDS =>$query,
    CURLOPT_HTTPHEADER => array(
      "x-api-key: $APIKEY",
      'Content-Type: application/json'
    ),
  ));

  $response = curl_exec($curl);

  curl_close($curl);
echo $response;
}
$simItem = '{"query":"query MyQuery {\\r\\n  similarItems(itemId: \\"1\\") {\\r\\n    items\\r\\n  }\\r\\n}\\r\\n","variables":{}}';
$persItems = '{"query":"query MyQuery {\\r\\n  userPersonalizations(userId: \\"\\") {\\r\\n    items\\r\\n  }\\r\\n}\\r\\n","variables":{}}';

ApiCall("Similar Items",$simItem);
ApiCall("Personalized Items",$simItem);

?>


