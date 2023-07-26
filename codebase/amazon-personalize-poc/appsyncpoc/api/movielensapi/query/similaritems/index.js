exports.handler = async (event) => {
    return {"items": [event.itemId, 100, 200, 300, 400]};
};